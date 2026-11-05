from requirements_architect.generators import mermaid


def test_label_strips_everything_that_could_break_out_or_inject():
    evil = 'x"] --> Z["pwned\n%%{init: {"theme":"x"}}%%\nclick A call alert()'
    out = mermaid.label(evil)
    for bad in ('"', "[", "]", "{", "}", "%%", "\n", ";", "<", ">", "`"):
        assert bad not in out
    assert mermaid.label("") == "unnamed" and mermaid.label('"""') == "unnamed"


def test_label_truncates():
    assert len(mermaid.label("a" * 500, 30)) == 30 and mermaid.label("a" * 500, 30).endswith("…")


def test_node_id_is_safe():
    assert mermaid.node_id("C-001") == "C001"
    assert mermaid.node_id("1-2") == "n12"
    assert mermaid.node_id('a b"c') == "abc"


def test_flowchart_drops_edges_to_unknown_nodes_and_sanitizes_text():
    out = mermaid.flowchart(
        [("C-001", 'A "quoted" [name]'), ("C-002", "B")],
        [("C-001", "C-002", 'uses "x"'), ("C-001", "C-999", None), ("C-999", "C-002", None)],
    )
    lines = out.splitlines()
    assert lines[0] == "flowchart LR"
    assert sum("-->" in ln for ln in lines) == 1  # only the valid edge survives
    assert 'C001["A quoted name"]' in out and "C999" not in out


def test_sequence_and_er_render_only_known_participants():
    seq = mermaid.sequence(
        [("C-001", "A"), ("C-002", "B")], [("C-001", "C-002", "hello"), ("C-001", "C-9", "x")]
    )
    assert (
        seq.splitlines()[0] == "sequenceDiagram" and "C001->>C002: hello" in seq and "C9" not in seq
    )
    er = mermaid.er_diagram(
        [("users", [("uuid", "id")]), ("orders", [("uuid", "id"), ("uuid", "user_id")])],
        [("orders", "users", "placed by"), ("orders", "ghost", "x")],
    )
    assert (
        er.startswith("erDiagram")
        and 'orders }o--|| users : "placed by"' in er
        and "ghost" not in er
    )
