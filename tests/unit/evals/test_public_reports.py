from pathlib import Path

from roboclaws.evals.public_reports import publish_report_bundle, sanitize_report_html


def test_sanitize_report_html_removes_private_sections_and_prompt() -> None:
    source = (
        '<section class="rerun-panel">rerun</section>'
        '<details class="summary-metadata"><summary>Task prompt</summary>secret</details>'
        '<section class="panel private-evaluation"><h2>Private Evaluation</h2>truth</section>'
        '<a href="runs/sample/run_result.json">internal result</a>'
        '<section class="panel">public screenshot</section>'
    )
    rendered = sanitize_report_html(source)
    assert "rerun" not in rendered
    assert "secret" not in rendered
    assert "truth" not in rendered
    assert 'href="runs/sample/run_result.json"' not in rendered
    assert "internal result" in rendered
    assert "public screenshot" in rendered


def test_publish_report_bundle_copies_html_images_and_excludes_private(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "site"
    (source / "runs" / "sample").mkdir(parents=True)
    (source / "runs" / "sample" / "report.html").write_text("<html>public</html>")
    (source / "runs" / "sample" / "after.png").write_bytes(b"png")
    (source / "runs" / "sample" / "trace.jsonl").write_text("private")
    (source / "runs" / "sample" / "private_evaluation.json").write_text("private")
    assert publish_report_bundle(source, destination) == 2
    assert (destination / "runs" / "sample" / "report.html").is_file()
    assert (destination / "runs" / "sample" / "after.png").is_file()
    assert not (destination / "runs" / "sample" / "trace.jsonl").exists()
