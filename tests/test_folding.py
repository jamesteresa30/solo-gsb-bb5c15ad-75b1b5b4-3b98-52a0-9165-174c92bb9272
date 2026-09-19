"""核心展开逻辑测试。"""
import pytest

from app.folding import FoldError, fold_point, fold_regions, plan_punches, unfold_board


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


def test_fold_point_matches_unfold_paths():
    # 展开结果中的每个孔位，正向折叠后必须回到原打孔点
    regions = fold_regions(8, 4, ["left", "down"])
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    for hole in res["holes"]:
        assert fold_point(regions, ["left", "down"], hole["x"], hole["y"]) == (1, 2)


def test_plan_punches_round_trip_single_orbit():
    # 与 test_unfold_left_down_known_coordinates 互逆
    res = plan_punches(8, 4, ["left", "down"], [(1, 1), (1, 2), (6, 1), (6, 2)])
    assert res["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert res["stack_layers"] == 4
    assert res["target_count"] == 4
    assert res["punch_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0}]


def test_plan_punches_multiple_orbits_sorted():
    targets = [
        (1, 0), (1, 3), (2, 0), (2, 3),  # 等价组 (1, 1)
        (0, 1), (0, 2), (3, 1), (3, 2),  # 等价组 (0, 0)
    ]
    res = plan_punches(4, 4, ["left", "down"], targets)
    assert res["target_count"] == 8
    assert res["punch_count"] == 2
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 1, "y": 1}]


def test_plan_punches_no_folds_dedup_and_sort():
    res = plan_punches(3, 3, [], [(2, 1), (0, 0), (2, 1)])
    assert res["stack_layers"] == 1
    assert res["target_count"] == 2
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 2, "y": 1}]


def test_plan_punches_result_feeds_unfold_board():
    targets = [(1, 1), (1, 2), (6, 1), (6, 2)]
    res = plan_punches(8, 4, ["left", "down"], targets)
    punches = [(p["x"], p["y"]) for p in res["punches"]]
    unfolded = unfold_board(8, 4, ["left", "down"], punches)
    assert {(h["x"], h["y"]) for h in unfolded["holes"]} == set(targets)


def test_plan_punches_target_out_of_bounds():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, ["left"], [(1, 1), (9, 0), (0, 4)])
    err = exc_info.value
    assert err.code == "target_out_of_bounds"
    # 越界坐标去重后按 (x, y) 排序全部列出
    assert err.context["out_of_bounds"] == [{"x": 0, "y": 4}, {"x": 9, "y": 0}]
    assert err.context["board_width"] == 4
    assert err.context["board_height"] == 4


def test_plan_punches_incomplete_group_reports_missing():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(1, 1)])
    err = exc_info.value
    assert err.code == "incomplete_equivalence_group"
    assert err.context["group"] == {"x": 1, "y": 0}
    assert err.context["missing"] == [
        {"x": 1, "y": 2},
        {"x": 6, "y": 1},
        {"x": 6, "y": 2},
    ]
    assert err.context["extra"] == []


def test_plan_punches_reports_first_incomplete_group_sorted():
    # (6, 1) 归并到组 (1, 0)，(0, 3) 归并到组 (0, 1)；两组都不完整时报告 (x, y) 最小者
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(6, 1), (0, 3)])
    err = exc_info.value
    assert err.code == "incomplete_equivalence_group"
    assert err.context["group"] == {"x": 0, "y": 1}
    assert err.context["missing"] == [
        {"x": 0, "y": 0},
        {"x": 7, "y": 0},
        {"x": 7, "y": 3},
    ]


def test_plan_punches_odd_axis_propagates():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(3, 2, ["left"], [(0, 0)])
    assert exc_info.value.code == "odd_fold_axis"


def test_plan_punches_limit_exceeded():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, [], [(0, 0), (1, 1)], max_punches=1)
    assert exc_info.value.code == "limit_exceeded"

    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, ["left"], [(0, 0), (1, 0)], max_total_holes=3)
    assert exc_info.value.code == "limit_exceeded"
