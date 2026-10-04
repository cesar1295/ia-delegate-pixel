from aidelegate.summary import trim


def test_short_text_untouched():
    assert trim("a\nb\n", 15) == ("a\nb", False)


def test_long_text_is_cut():
    text = "\n".join(str(i) for i in range(40))
    out, cut = trim(text, 15)
    assert cut is True
    assert out.splitlines() == [str(i) for i in range(15)]


def test_exact_limit_not_marked_as_cut():
    assert trim("\n".join("x" * 15), 15)[1] is False


def test_empty():
    assert trim("", 15) == ("", False)


def test_garbled_markdown_links():
    from aidelegate.summary import looks_garbled

    resumen = (
        "- En [routing.py](file:///home/usuario/.local/share/ai-delegate/worktrees/20261004-154459-ai-delegate-agy/aidelegate/routing.py#L182-L200), corregí la función.\n"
        "- En [loop.py](file:///home/usuario/.local/share/ai-delegate/worktrees/20261004-154459-ai-delegate-agy/aidelegate/loop.py#L75), eliminé el argumento inexistente.\n"
        "- Archivos tocados: [aidelegate/routing.py](file:///home/usuario/.local/share/ai-delegate/worktrees/20261004-154459-ai-delegate-agy/aidelegate/routing.py) y [aidelegate/loop.py](file:///home/usuario/.local/share/ai-delegate/worktrees/20261004-154459-ai-delegate-agy/aidelegate/loop.py).\n"
        "- Verificación: validación de lógica y diff estricto con git diff.\n"
    )
    assert not looks_garbled(resumen)
    assert looks_garbled("a" * 300)
