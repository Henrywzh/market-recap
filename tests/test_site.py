from market_recap import site


def test_code_version_moves_with_the_scripts(tmp_path):
    js = tmp_path / "js" / "tabs"
    js.mkdir(parents=True)
    (js / "a.js").write_text("export default 1;\n")
    first = site.code_version(tmp_path)
    assert first == site.code_version(tmp_path)
    (js / "a.js").write_text("export default 2;\n")
    assert site.code_version(tmp_path) != first


def test_built_index_carries_the_code_version(tmp_path):
    site.build(dist=tmp_path / "dist")
    index = (tmp_path / "dist" / "index.html").read_text()
    assert site.CODE_VERSION_PLACEHOLDER not in index
    assert site.code_version() in index
