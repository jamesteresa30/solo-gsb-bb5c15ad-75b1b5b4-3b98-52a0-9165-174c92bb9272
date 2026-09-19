"""核心折叠 / 展开 / 反向打孔规划逻辑（纯 Python，不依赖 Web 框架）。

坐标约定：
- 板材为整数网格，单元格坐标 (x, y)，x 向右、y 向下，左上角为 (0, 0)。
- 打孔点使用最终折叠面的局部坐标，(0, 0) 为折叠面左上角。
- 展开结果中的孔位与规划接口的目标孔位均使用原始板材坐标。

折叠方向语义（被移动的一半朝该方向折）：
- left  ：右半部分向左折，折叠面落在左半区；
- right ：左半部分向右折，折叠面落在右半区；
- up    ：下半部分向上折，折叠面落在上半区；
- down  ：上半部分向下折，折叠面落在下半区。
"""
from __future__ import annotations

from dataclasses import dataclass

HORIZONTAL_FOLDS = {"left", "right"}  # 沿竖直轴对折，改变宽度
VERTICAL_FOLDS = {"up", "down"}       # 沿水平轴对折，改变高度


class FoldError(ValueError):
    """折叠序列校验或展开过程中抛出的领域错误。"""

    def __init__(self, code: str, message: str, **context):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class Region:
    """原始板材上的轴对齐网格区域。"""

    x: int
    y: int
    width: int
    height: int


def fold_regions(width: int, height: int, folds: list[str]) -> list[Region]:
    """计算每一次对折后板材占据的区域。

    返回长度为 len(folds) + 1 的列表：regions[0] 为整张板材，
    regions[i + 1] 为应用 folds[i] 之后的区域。

    当某一步的折叠轴长度为奇数时抛出 FoldError("odd_fold_axis")。
    """
    regions = [Region(0, 0, width, height)]
    for i, direction in enumerate(folds):
        cur = regions[-1]
        if direction in HORIZONTAL_FOLDS:
            if cur.width % 2:
                raise FoldError(
                    "odd_fold_axis",
                    f"第 {i} 步折叠（'{direction}'）要求当前宽度为偶数，实际为 {cur.width}。",
                    step=i,
                    direction=direction,
                    axis="width",
                    axis_length=cur.width,
                )
            half = cur.width // 2
            x = cur.x if direction == "left" else cur.x + half
            regions.append(Region(x, cur.y, half, cur.height))
        else:
            if cur.height % 2:
                raise FoldError(
                    "odd_fold_axis",
                    f"第 {i} 步折叠（'{direction}'）要求当前高度为偶数，实际为 {cur.height}。",
                    step=i,
                    direction=direction,
                    axis="height",
                    axis_length=cur.height,
                )
            half = cur.height // 2
            y = cur.y if direction == "up" else cur.y + half
            regions.append(Region(cur.x, y, cur.width, half))
    return regions


def unfold_board(
    width: int,
    height: int,
    folds: list[str],
    punches: list[tuple[int, int]],
) -> dict:
    """逆序展开折叠序列，通过镜像传播孔位。

    参数：
        width/height：原始板材的整数网格尺寸。
        folds：按执行顺序给出的折叠方向序列。
        punches：最终折叠面上的打孔点（折叠面局部坐标）。

    返回：
        包含 final_face、stack_layers、total_holes、unique_holes、holes 的字典。
        重合坐标被合并为一个 hole，其 paths 保留每一条传播路径。
    """
    regions = fold_regions(width, height, folds)
    final = regions[-1]

    for idx, (px, py) in enumerate(punches):
        if not (0 <= px < final.width and 0 <= py < final.height):
            raise FoldError(
                "punch_out_of_bounds",
                f"打孔点 #{idx} ({px}, {py}) 超出最终折叠面范围 "
                f"（{final.width}x{final.height}，局部坐标从 0 开始）。",
                punch=idx,
                x=px,
                y=py,
                face_width=final.width,
                face_height=final.height,
            )

    # 状态项：(x, y, 打孔点索引, 传播步骤)。步骤按展开顺序（最后一次折叠在前）追加。
    states: list[tuple[int, int, int, list[dict]]] = [
        (final.x + px, final.y + py, idx, []) for idx, (px, py) in enumerate(punches)
    ]

    for i in range(len(folds) - 1, -1, -1):
        direction = folds[i]
        before = regions[i]  # 该次折叠之前（即展开之后）的区域
        nxt: list[tuple[int, int, int, list[dict]]] = []
        for x, y, idx, steps in states:
            stay = {"fold": i, "direction": direction, "branch": "stay"}
            mirror = {"fold": i, "direction": direction, "branch": "mirror"}
            # 未移动的那一层：坐标不变
            nxt.append((x, y, idx, steps + [stay]))
            # 被折过来的那一层：关于折叠轴镜像
            if direction in HORIZONTAL_FOLDS:
                mx = 2 * before.x + before.width - 1 - x
                nxt.append((mx, y, idx, steps + [mirror]))
            else:
                my = 2 * before.y + before.height - 1 - y
                nxt.append((x, my, idx, steps + [mirror]))
        states = nxt

    # 合并重合坐标，保留各自传播路径
    merged: dict[tuple[int, int], list[dict]] = {}
    for x, y, idx, steps in states:
        path = {
            "punch": idx,
            "punch_point": {"x": punches[idx][0], "y": punches[idx][1]},
            # 反转为请求中折叠的原始顺序，便于阅读
            "steps": list(reversed(steps)),
        }
        merged.setdefault((x, y), []).append(path)

    holes = [
        {"x": x, "y": y, "layers": len(paths), "paths": paths}
        for (x, y), paths in sorted(merged.items())
    ]
    return {
        "final_face": {
            "x": final.x,
            "y": final.y,
            "width": final.width,
            "height": final.height,
        },
        "stack_layers": 1 << len(folds),
        "total_holes": len(states),
        "unique_holes": len(holes),
        "holes": holes,
    }


def fold_point(regions: list[Region], folds: list[str], x: int, y: int) -> tuple[int, int]:
    """将原始板材坐标 (x, y) 沿折叠序列正向映射到最终折叠面（仍为板材坐标）。

    每步折叠中，位于被移动半区的点关于折叠轴镜像，其余点保持不动；
    与 unfold_board 的逆序镜像传播互为逆过程。
    """
    for i, direction in enumerate(folds):
        before = regions[i]
        if direction in HORIZONTAL_FOLDS:
            half = before.width // 2
            moved = x >= before.x + half if direction == "left" else x < before.x + half
            if moved:
                x = 2 * before.x + before.width - 1 - x
        else:
            half = before.height // 2
            moved = y >= before.y + half if direction == "up" else y < before.y + half
            if moved:
                y = 2 * before.y + before.height - 1 - y
    return x, y


def plan_punches(
    width: int,
    height: int,
    folds: list[str],
    targets: list[tuple[int, int]],
    *,
    max_punches: int | None = None,
    max_total_holes: int | None = None,
) -> dict:
    """反向打孔规划：由期望的展开孔位反推最终折叠面上的最小打孔点集合。

    流程：
    1. 目标孔位去重并做板材边界校验；
    2. 沿折叠序列把每个目标孔位正向归并到最终折叠面的等价位置，
       相同位置构成一个等价组，组代表即候选打孔点；
    3. 复用 unfold_board 对候选打孔点复算展开结果；
    4. 仅当每个等价组都形成完整镜像轨道（复算集合与目标集合完全一致）
       时，返回按 (x, y) 稳定排序的最小打孔点列表。

    异常：
        FoldError("target_out_of_bounds")：目标含越界坐标，
            context 的 out_of_bounds 列出全部越界点。
        FoldError("incomplete_equivalence_group")：首个不完整等价组，
            context 列出该组缺失 / 多余坐标，绝不默默补孔。
        FoldError("limit_exceeded")：归并后的打孔点数或展开孔位总数超限。
    """
    regions = fold_regions(width, height, folds)
    final = regions[-1]

    # 目标孔位去重，统一按 (x, y) 排序保证后续处理顺序稳定
    unique_targets = sorted(set(targets))

    out_of_bounds = [
        (x, y) for x, y in unique_targets if not (0 <= x < width and 0 <= y < height)
    ]
    if out_of_bounds:
        raise FoldError(
            "target_out_of_bounds",
            f"目标孔位包含 {len(out_of_bounds)} 个越界坐标"
            f"（板材 {width}x{height}，坐标从 0 开始）。",
            out_of_bounds=[{"x": x, "y": y} for x, y in out_of_bounds],
            board_width=width,
            board_height=height,
        )

    def to_local(x: int, y: int) -> tuple[int, int]:
        """板材坐标 -> 最终折叠面局部坐标。"""
        fx, fy = fold_point(regions, folds, x, y)
        return fx - final.x, fy - final.y

    # 沿折叠过程归并：等价组（折叠面局部坐标）-> 组内目标孔位
    members_by_punch: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for target in unique_targets:
        members_by_punch.setdefault(to_local(*target), set()).add(target)
    punches = sorted(members_by_punch)

    if max_punches is not None and len(punches) > max_punches:
        raise FoldError(
            "limit_exceeded",
            f"归并后打孔点数 {len(punches)} 超过上限 MAX_PUNCHES={max_punches}。",
        )
    if max_total_holes is not None:
        total = len(punches) << len(folds)
        if total > max_total_holes:
            raise FoldError(
                "limit_exceeded",
                f"展开后将产生 {total} 个孔位，超过上限 "
                f"MAX_TOTAL_HOLES={max_total_holes}，请减少折叠步数或目标孔位。",
            )

    # 用现有展开逻辑复算，并把复算孔位归并回各自等价组（即完整镜像轨道）
    recomputed = unfold_board(width, height, folds, punches)
    orbit_by_punch: dict[tuple[int, int], set[tuple[int, int]]] = {
        punch: set() for punch in punches
    }
    for hole in recomputed["holes"]:
        orbit_by_punch[to_local(hole["x"], hole["y"])].add((hole["x"], hole["y"]))

    # 按 (x, y) 顺序找到首个不完整等价组，列出缺失 / 多余坐标
    for punch in punches:
        orbit = orbit_by_punch[punch]
        members = members_by_punch[punch]
        missing = sorted(orbit - members)  # 轨道中未被目标覆盖的对称孔
        extra = sorted(members - orbit)    # 目标中不属于该轨道的孔（结构性为空，防御保留）
        if missing or extra:
            raise FoldError(
                "incomplete_equivalence_group",
                f"等价组 ({punch[0]}, {punch[1]}) 的镜像轨道不完整："
                f"缺失 {len(missing)} 个、多余 {len(extra)} 个坐标；"
                "请补全或移除后重试，服务端不会自动补孔。",
                group={"x": punch[0], "y": punch[1]},
                missing=[{"x": x, "y": y} for x, y in missing],
                extra=[{"x": x, "y": y} for x, y in extra],
            )

    # 组完整性已保证复算集合与目标集合一致，此处为防御性校验
    target_set = set(unique_targets)
    recomputed_set = {(h["x"], h["y"]) for h in recomputed["holes"]}
    if recomputed_set != target_set:
        raise FoldError(
            "target_mismatch",
            "复算结果与目标集合不一致。",
            missing=[{"x": x, "y": y} for x, y in sorted(target_set - recomputed_set)],
            extra=[{"x": x, "y": y} for x, y in sorted(recomputed_set - target_set)],
        )

    return {
        "final_face": {
            "x": final.x,
            "y": final.y,
            "width": final.width,
            "height": final.height,
        },
        "stack_layers": 1 << len(folds),
        "target_count": len(unique_targets),
        "punch_count": len(punches),
        "punches": [{"x": x, "y": y} for x, y in punches],
    }
