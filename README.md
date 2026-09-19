# 包装板材折叠打孔模板展开 API

基于 Python + FastAPI 的 HTTP 服务：客户端提交整数网格矩形板材、依次执行的上下/左右对折方向，以及最终折叠面上的打孔点；服务端**逆序展开**折叠序列，通过**镜像传播**孔位，自动**拒绝当前折叠轴长度为奇数**的折叠步骤，并将展开后**重合的坐标合并**（各自传播路径完整保留）。

返回内容：展开后的唯一孔位、每个孔位的覆盖层数，以及每个孔位的来源路径（来自哪个打孔点、每一步折叠走了哪一侧）。

此外提供**反向打孔规划**接口 `POST /api/v1/punch-plan`：给定期望出现在展开板材上的目标孔位，沿折叠过程归并到最终折叠面的等价位置并逐组校验镜像完整性，反推出最小且唯一的打孔点列表；目标缺少对称孔或含越界坐标时直接返回 400，**不会默默补孔**。

## 快速开始

只需一条命令（依赖随容器构建自动安装）：

```bash
docker compose up --build
```

启动后访问：

- API 交互文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 正向展开接口：`POST http://localhost:8000/api/v1/unfold`
- 反向打孔规划接口：`POST http://localhost:8000/api/v1/punch-plan`

停止服务：`docker compose down`。

## 配置

通过环境变量配置（可在 `compose.yaml` 的 `environment` 中修改）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_FOLDS` | `20` | 单次请求允许的最大折叠步数 |
| `MAX_PUNCHES` | `200` | 单次请求允许的最大打孔点数（`/unfold`） |
| `MAX_TARGETS` | `4096` | 单次请求允许的最大目标孔位数（`/punch-plan`，去重前） |
| `MAX_TOTAL_HOLES` | `200000` | 展开后孔位总数（打孔点数 × 2^折叠步数）上限；`/punch-plan` 中用于限制单个镜像轨道大小 |

端口映射在 `compose.yaml` 中为 `"8000:8000"`，如需修改对外端口，调整冒号左侧即可。

## API 说明

### `POST /api/v1/unfold`

**请求体**

```json
{
  "board": { "width": 8, "height": 4 },
  "folds": ["left", "down"],
  "punches": [{ "x": 1, "y": 0 }]
}
```

| 字段 | 说明 |
| --- | --- |
| `board` | 原始板材的整数网格尺寸，`width`/`height` 为正整数 |
| `folds` | 按执行顺序给出的对折方向：`up` / `down` / `left` / `right`，可为空数组 |
| `punches` | 最终折叠面上的打孔点，使用折叠面**局部坐标**（左上角为 `(0,0)`），至少 1 个 |

**坐标与折叠语义约定**

- 板材为整数网格，单元格坐标 `(x, y)`，`x` 向右、`y` 向下，左上角 `(0, 0)`。
- 折叠方向表示"被移动的一半朝该方向折"：`left` = 右半向左折；`right` = 左半向右折；`up` = 下半向上折；`down` = 上半向下折。
- 每次对折要求当前对应边长为**偶数**（左右折看当前宽度，上下折看当前高度），否则该步骤被拒绝并返回 400。
- 响应中的孔位坐标为**原始板材坐标系**。

**响应示例**（上面请求的返回，节选）

```json
{
  "final_face": { "x": 0, "y": 2, "width": 4, "height": 2 },
  "stack_layers": 4,
  "total_holes": 4,
  "unique_holes": 4,
  "holes": [
    {
      "x": 1,
      "y": 1,
      "layers": 1,
      "paths": [
        {
          "punch": 0,
          "punch_point": { "x": 1, "y": 0 },
          "steps": [
            { "fold": 0, "direction": "left", "branch": "stay" },
            { "fold": 1, "direction": "down", "branch": "mirror" }
          ]
        }
      ]
    }
  ]
}
```

| 响应字段 | 说明 |
| --- | --- |
| `final_face` | 最终折叠面在原始板材坐标系中的位置与尺寸 |
| `stack_layers` | 折叠后每处的纸层数 = 2^折叠步数 |
| `total_holes` / `unique_holes` | 展开孔位总数（按路径计）/ 去重后的唯一孔位数 |
| `holes[].layers` | 覆盖该坐标的传播路径数（重合次数） |
| `holes[].paths[]` | 来源路径：`punch` 为请求中打孔点下标；`steps` 按折叠原始顺序记录每一步的分支，`stay` = 未移动的一层，`mirror` = 被折过来的一层 |

**curl 示例**

```bash
curl -X POST http://localhost:8000/api/v1/unfold \
  -H "Content-Type: application/json" \
  -d '{
    "board": {"width": 8, "height": 4},
    "folds": ["left", "down"],
    "punches": [{"x": 1, "y": 0}]
  }'
```

**错误响应**

- `400 odd_fold_axis`：某一步折叠时当前轴长为奇数，`detail` 中带 `step` / `direction` / `axis` / `axis_length`。
- `400 punch_out_of_bounds`：打孔点超出最终折叠面范围。
- `400 limit_exceeded`：超出 `MAX_FOLDS` / `MAX_PUNCHES` / `MAX_TOTAL_HOLES` 限制。
- `422`：请求体不符合 schema（如非法方向、负坐标、空打孔列表）。

```json
{
  "detail": {
    "error": "odd_fold_axis",
    "message": "第 0 步折叠（'left'）要求当前宽度为偶数，实际为 3。",
    "step": 0,
    "direction": "left",
    "axis": "width",
    "axis_length": 3
  }
}
```

### `POST /api/v1/punch-plan`

反向打孔规划：已知希望在**展开后的原始板材**上出现哪些孔位，反推最终折叠面上应该在哪里打孔。

处理流程：

1. 目标孔位**去重**；
2. 沿折叠过程把每个目标孔位**正向归并**到最终折叠面的局部坐标，同一局部坐标的目标构成一个**等价组**；
3. 复用 `/api/v1/unfold` 的展开逻辑复算每个等价位置的**完整镜像轨道**，逐组核对目标集合是否与轨道**恰好相等**；
4. 仅当**每个等价组都完整**且整体复算结果与目标集合完全一致时，返回**最小且唯一**的打孔点列表（稳定按 `(x, y)` 排序）。

任何等价组缺少对称孔（或包含不属于该轨道的多余坐标）都会返回 400 并列出**首个不完整等价组**的 `missing` / `extra` 坐标，**服务端不会默默补孔**。

**请求体**

```json
{
  "board": { "width": 8, "height": 4 },
  "folds": ["left", "down"],
  "targets": [
    { "x": 1, "y": 1 },
    { "x": 1, "y": 2 },
    { "x": 6, "y": 1 },
    { "x": 6, "y": 2 }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `board` | 原始板材的整数网格尺寸，`width`/`height` 为正整数 |
| `folds` | 按执行顺序给出的对折方向：`up` / `down` / `left` / `right`，可为空数组 |
| `targets` | 期望在展开板材上出现的目标孔位，使用**原始板材坐标**（左上角 `(0,0)`），至少 1 个；重复坐标会被去重，必须全部落在板材范围内 |

**成功响应示例**（节选）

```json
{
  "final_face": { "x": 0, "y": 2, "width": 4, "height": 2 },
  "targets": [
    { "x": 1, "y": 1 },
    { "x": 1, "y": 2 },
    { "x": 6, "y": 1 },
    { "x": 6, "y": 2 }
  ],
  "punches": [{ "x": 1, "y": 0 }],
  "punch_count": 1,
  "stack_layers": 4,
  "total_holes": 4,
  "unique_holes": 4,
  "holes": [ ... ]
}
```

| 响应字段 | 说明 |
| --- | --- |
| `targets` | 去重并按 `(x, y)` 稳定排序后的目标孔位 |
| `punches` | 最小且唯一的打孔点列表（最终折叠面**局部坐标**，稳定排序）；其展开复算结果与 `targets` 完全一致 |
| `punch_count` | 去重后的打孔点数量 |
| `final_face` / `stack_layers` / `total_holes` / `unique_holes` / `holes` | 用规划出的打孔点调用展开逻辑的复算结果，字段含义同 `/api/v1/unfold` |

**curl 示例**

```bash
curl -X POST http://localhost:8000/api/v1/punch-plan \
  -H "Content-Type: application/json" \
  -d '{
    "board": {"width": 8, "height": 4},
    "folds": ["left", "down"],
    "targets": [
      {"x": 1, "y": 1}, {"x": 1, "y": 2},
      {"x": 6, "y": 1}, {"x": 6, "y": 2}
    ]
  }'
```

**缺少对称孔的错误响应**（上面请求去掉 `(6,2)` 时返回 400）

```json
{
  "detail": {
    "error": "incomplete_equivalence_group",
    "message": "折叠面等价位置 (1, 0) 的等价组未形成完整镜像轨道：缺失 1 个对称孔位，多余 0 个坐标；请补齐或修正目标，服务端不会自动补孔。",
    "equivalent": { "x": 1, "y": 0 },
    "missing": [{ "x": 6, "y": 2 }],
    "extra": []
  }
}
```

**错误响应**

- `400 incomplete_equivalence_group`：首个不完整等价组，`detail` 中带 `equivalent`（折叠面局部坐标）、`missing`（缺失的对称孔坐标）、`extra`（多余坐标）。
- `400 target_out_of_bounds`：目标孔位超出原始板材范围，带 `target` / `x` / `y` / `board_width` / `board_height`。
- `400 odd_fold_axis`：同 `/api/v1/unfold`。
- `400 limit_exceeded`：超出 `MAX_FOLDS` / `MAX_TARGETS` / `MAX_TOTAL_HOLES` 限制。
- `422`：请求体不符合 schema（如非法方向、负坐标、空目标列表）。

## 本地开发（不用 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                   # 运行测试
uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
app/
  main.py       # FastAPI 入口与路由
  models.py     # Pydantic 请求/响应模型
  folding.py    # 核心折叠/展开逻辑（纯 Python，可独立测试）
tests/
  test_api.py   # HTTP 接口测试
Dockerfile
compose.yaml
requirements.txt        # 运行时依赖
requirements-dev.txt    # 开发/测试依赖
```
