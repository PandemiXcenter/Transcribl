from importlib.resources import files


def asset(name: str) -> str:
    return files("transcribl.interfaces.desktop").joinpath("static", name).read_text("utf-8")
