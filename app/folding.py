"""核心折叠 / 展开逻辑（纯 Python，不依赖 Web 框架）。

坐标约定：
- 板材为整数网格，单元格坐标 (x, y)，x 向右、y 向下，左上角为 (0, 0)。
- 打孔点使用最终折叠面的局部坐标，(0, 0) 为折叠面左上角。
- 展开结果中的孔位使用原始板材坐标。

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
