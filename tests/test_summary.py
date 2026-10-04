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
