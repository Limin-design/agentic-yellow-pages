import pytest
from utils import clean_x_handle

def test_clean_x_handle_none():
    assert clean_x_handle(None) is None

def test_clean_x_handle_non_string():
    assert clean_x_handle(123) is None
    assert clean_x_handle([]) is None

def test_clean_x_handle_empty_string():
    assert clean_x_handle("") is None
    assert clean_x_handle("   ") is None

def test_clean_x_handle_valid_simple():
    assert clean_x_handle("user") == "@user"
    assert clean_x_handle("@user") == "@user"

def test_clean_x_handle_whitespace():
    assert clean_x_handle("  user  ") == "@user"
    assert clean_x_handle(" @user ") == "@user"

def test_clean_x_handle_x_url():
    assert clean_x_handle("https://x.com/user") == "@user"
    assert clean_x_handle("x.com/user") == "@user"

def test_clean_x_handle_twitter_url():
    assert clean_x_handle("https://twitter.com/user") == "@user"
    assert clean_x_handle("twitter.com/user") == "@user"

def test_clean_x_handle_url_with_query():
    assert clean_x_handle("https://x.com/user?s=20") == "@user"
    assert clean_x_handle("https://twitter.com/user?foo=bar&baz=qux") == "@user"

def test_clean_x_handle_url_trailing_slash():
    assert clean_x_handle("https://x.com/user/") == "@user"

def test_clean_x_handle_just_at():
    assert clean_x_handle("@") is None

def test_clean_x_handle_url_just_domain():
    assert clean_x_handle("https://x.com/") is None
    assert clean_x_handle("https://twitter.com") is None
