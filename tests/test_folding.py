"""核心展开逻辑测试。"""
import pytest

from app.folding import FoldError, fold_regions, plan_punches, unfold_board


def test_unfold_left_down_known_coordinates():
    # 8x4 板材：右半向左折 -> 上半向下折；折叠面为 x∈[0,4), y∈[2,4)
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    assert res["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert res["stack_layers"] == 4
    assert res["total_holes"] == 4
    assert res["unique_holes"] == 4
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(1, 1), (1, 2), (6, 1), (6, 2)}
    for hole in res["holes"]:
        assert hole["layers"] == 1
        assert len(hole["paths"]) == 1
        path = hole["paths"][0]
        assert path["punch"] == 0
        assert path["punch_point"] == {"x": 1, "y": 0}
        # 步骤按折叠原始顺序排列
        assert [s["fold"] for s in path["steps"]] == [0, 1]


def test_path_branches_recorded():
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    by_coord = {(h["x"], h["y"]): h for h in res["holes"]}
    # (6, 1) 是两次都取镜像分支的孔位
    steps = by_coord[(6, 1)]["paths"][0]["steps"]
    assert [s["branch"] for s in steps] == ["mirror", "mirror"]
    assert [s["direction"] for s in steps] == ["left", "down"]
    # (1, 2) 是两次都留在原层的孔位
    steps = by_coord[(1, 2)]["paths"][0]["steps"]
    assert [s["branch"] for s in steps] == ["stay", "stay"]


def test_fold_right_semantics():
    # 4x1：左半向右折，折叠面为 x∈[2,4)
    res = unfold_board(4, 1, ["right"], [(0, 0)])
    assert res["final_face"] == {"x": 2, "y": 0, "width": 2, "height": 1}
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(1, 0), (2, 0)}


def test_fold_up_semantics():
    # 1x4：下半向上折，折叠面为 y∈[0,2)
    res = unfold_board(1, 4, ["up"], [(0, 1)])
    assert res["final_face"] == {"x": 0, "y": 0, "width": 1, "height": 2}
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(0, 1), (0, 2)}


def test_no_folds_passthrough():
    res = unfold_board(3, 3, [], [(2, 1)])
    assert res["stack_layers"] == 1
    assert res["unique_holes"] == 1
    hole = res["holes"][0]
    assert (hole["x"], hole["y"], hole["layers"]) == (2, 1, 1)
    assert hole["paths"][0]["steps"] == []


def test_odd_axis_rejected_at_first_step():
    with pytest.raises(FoldError) as exc_info:
        unfold_board(8, 5, ["up"], [(0, 0)])
    err = exc_info.value
    assert err.code == "odd_fold_axis"
    assert err.context["step"] == 0
    assert err.context["axis"] == "height"
    assert err.context["axis_length"] == 5


def test_odd_axis_rejected_at_later_step():
    # 6 -> 3 之后宽度为奇数，第二步应被拒绝
    with pytest.raises(FoldError) as exc_info:
        unfold_board(6, 2, ["left", "left"], [(0, 0)])
    err = exc_info.value
    assert err.code == "odd_fold_axis"
    assert err.context["step"] == 1
    assert err.context["axis_length"] == 3


def test_punch_out_of_bounds():
    with pytest.raises(FoldError) as exc_info:
        unfold_board(4, 4, ["left"], [(2, 0)])  # 折叠面宽 2，x=2 越界
    assert exc_info.value.code == "punch_out_of_bounds"
    assert exc_info.value.context["punch"] == 0


def test_duplicate_punches_merge_but_keep_paths():
    res = unfold_board(4, 2, ["left"], [(1, 0), (1, 0)])
    assert res["total_holes"] == 4
    assert res["unique_holes"] == 2
    for hole in res["holes"]:
        assert hole["layers"] == 2
        assert len(hole["paths"]) == 2
        assert {p["punch"] for p in hole["paths"]} == {0, 1}


def test_multiple_distinct_punches():
    res = unfold_board(4, 4, ["left", "down"], [(0, 0), (1, 1)])
    assert res["stack_layers"] == 4
    assert res["total_holes"] == 8
    assert res["unique_holes"] == 8


def test_fold_regions_sequence():
    regions = fold_regions(8, 4, ["left", "down"])
    assert [(r.x, r.y, r.width, r.height) for r in regions] == [
        (0, 0, 8, 4),
        (0, 0, 4, 4),
        (0, 2, 4, 2),
    ]


# ---------------------------------------------------------------------------
# 反向打孔规划 plan_punches
# ---------------------------------------------------------------------------


def test_plan_roundtrip_matches_unfold_orbit():
    orbit = [(1, 1), (1, 2), (6, 1), (6, 2)]
    res = plan_punches(8, 4, ["left", "down"], orbit)
    assert res["punch_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0}]
    # targets 稳定排序
    assert res["targets"] == [{"x": x, "y": y} for x, y in sorted(orbit)]
    # 复算结果与目标集合完全一致
    assert {(h["x"], h["y"]) for h in res["holes"]} == set(orbit)


def test_plan_targets_deduplicated():
    res = plan_punches(
        8,
        4,
        ["left", "down"],
        [(6, 2), (1, 1), (1, 1), (6, 1), (1, 2), (6, 2)],
    )
    assert res["punch_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0}]
    assert len(res["targets"]) == 4


def test_plan_multiple_equivalence_groups():
    # 4x2 left：final face 为 x∈[0,2)；轨道分别为 {0,3}、{1,2}
    res = plan_punches(4, 2, ["left"], [(3, 0), (2, 1), (0, 0), (1, 1)])
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 1, "y": 1}]
    assert res["punch_count"] == 2
    assert res["unique_holes"] == 4


def test_plan_missing_symmetric_hole():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(1, 1), (1, 2), (6, 1)])
    err = exc_info.value
    assert err.code == "incomplete_equivalence_group"
    assert err.context["equivalent"] == {"x": 1, "y": 0}
    assert err.context["missing"] == [{"x": 6, "y": 2}]
    assert err.context["extra"] == []


def test_plan_reports_first_incomplete_group_in_sorted_order():
    # (2,1)/(5,1) 属于等价组 (2,0)（同样不完整），(1,*)/(6,1) 属于 (1,0)；
    # 等价组按局部坐标排序，(1,0) 在前，故先报告它缺失 (6,2)。
    with pytest.raises(FoldError) as exc_info:
        plan_punches(
            8,
            4,
            ["left", "down"],
            [(2, 1), (5, 1), (1, 1), (1, 2), (6, 1)],
        )
    err = exc_info.value
    assert err.code == "incomplete_equivalence_group"
    assert err.context["equivalent"] == {"x": 1, "y": 0}
    assert err.context["missing"] == [{"x": 6, "y": 2}]


def test_plan_target_out_of_bounds():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, ["left"], [(4, 0)])
    err = exc_info.value
    assert err.code == "target_out_of_bounds"
    assert err.context["target"] == 0
    assert err.context["x"] == 4
    assert err.context["y"] == 0


def test_plan_no_folds_passthrough():
    res = plan_punches(3, 3, [], [(2, 1), (2, 1)])
    assert res["punches"] == [{"x": 2, "y": 1}]
    assert res["targets"] == [{"x": 2, "y": 1}]
    assert res["punch_count"] == 1


def test_plan_all_fold_directions_roundtrip():
    # 用 unfold 生成轨道，再规划，必须回到同一组打孔点
    cases = [
        (["right"], (4, 1), [(0, 0), (1, 0)]),
        (["up"], (1, 4), [(0, 0), (0, 1)]),
        (["down"], (4, 4), [(0, 0), (1, 1)]),
        (["right", "up"], (8, 6), [(0, 0), (1, 1)]),
    ]
    for folds, board, punches in cases:
        w, h = board
        forward = unfold_board(w, h, folds, punches)
        orbit = [(hole["x"], hole["y"]) for hole in forward["holes"]]
        plan = plan_punches(w, h, folds, orbit)
        assert plan["punches"] == [{"x": x, "y": y} for x, y in sorted(punches)]
        assert {(p["x"], p["y"]) for p in plan["targets"]} == set(orbit)


def test_plan_odd_axis_rejected():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(3, 2, ["left"], [(0, 0), (2, 0)])
    assert exc_info.value.code == "odd_fold_axis"


def test_plan_partial_orbits_from_two_groups():
    # 两组各只给一个点，首个（按局部坐标排序）不完整组即报错
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 2, ["left"], [(0, 0), (2, 0)])
    err = exc_info.value
    assert err.code == "incomplete_equivalence_group"
    # 局部 (0,0) 的轨道是 {(0,0),(3,0)}
    assert err.context["equivalent"] == {"x": 0, "y": 0}
    assert err.context["missing"] == [{"x": 3, "y": 0}]
