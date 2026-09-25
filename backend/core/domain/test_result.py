from core.domain.result import Err, err_detail


def test_an_error_without_french_still_builds():
    err = Err("NOT_FOUND", "user 1 not found")
    assert err.message_fr is None


def test_the_detail_carries_both_languages():
    err = Err("NOT_FOUND", "user 1 not found", "utilisateur 1 introuvable")
    assert err_detail(err) == {"code": "NOT_FOUND", "message": "user 1 not found", "message_fr": "utilisateur 1 introuvable"}


def test_the_detail_of_an_untranslated_error_says_so_with_none():
    assert err_detail(Err("X", "english only")) == {"code": "X", "message": "english only", "message_fr": None}
