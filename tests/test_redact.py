"""What's blanked before a prompt goes to a hosted model, on synthetic text: each kind of number
and secret, and as many look-alikes that stay. Keys are put together here, never written whole,
so nothing in the repo reads as a real one."""

import time

import pytest

from proxenos.redact import redact

RANDOM = "x9Fq2LmZ7pR4vT8nB3kW6hJ1sD5gY0cE2aQ"  # 35 characters with no word in them


def blanked(text, keep=()):
    return redact(text, keep)[0]


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Card: 4111 1111 1111 1111 exp 12/27", "Card: [card number] exp 12/27"),
        ("card 4111111111111111.", "card [card number]."),
        ("Mastercard 5500-0000-0000-0004, thanks", "Mastercard [card number], thanks"),
        ("amex 3782 822463 10005", "amex [card number]"),
        ("Card: 4111 1111 1111 1111 12/27", "Card: [card number] 12/27"),  # expiry after
        ("call 555 4111 1111 1111 1111", "call 555 [card number]"),  # a number before
        ("4111 1111 1111 1111 5500 0000 0000 0004", "[card number] [card number]"),
    ],
)
def test_card_numbers_that_pass_the_luhn_check_are_blanked(text, shown):
    assert blanked(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("SSN 123-45-6789 thanks", "SSN [SSN] thanks"),
        ("SSN: 123456789", "SSN: [SSN]"),
        ("social security number 123 45 6789.", "social security number [SSN]."),
    ],
)
def test_social_security_numbers_are_blanked(text, shown):
    assert blanked(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Your verification code is 482913", "Your verification code is [code]"),
        ("verification code: 482913", "verification code: [code]"),
        ("G-482913 is your Google verification code.", "[code] is your Google verification code."),
        ("Your Uber code: 4829", "Your Uber code: [code]"),
        ("Your Apple ID Code is: 551234", "Your Apple ID Code is: [code]"),
        ("Use 482913 to sign in", "Use [code] to sign in"),
        ("Your OTP is 482913.", "Your OTP is [code]."),
        ("Your one-time passcode is 482 913", "Your one-time passcode is [code]"),
        ("Your login code for Acme is A7K9Q2", "Your login code for Acme is [code]"),
        ("PIN: 4829", "PIN: [code]"),
        ("CVV 123", "CVV [code]"),
    ],
)
def test_one_time_codes_are_blanked_in_the_usual_phrasings(text, shown):
    assert blanked(text) == shown


def test_keys_and_tokens_are_blanked_by_their_prefixes_and_labels():
    keys = [
        "sk-" + "ant-api03-" + "Ab3dE" * 8,
        "sk-" + "proj-" + "Qw9eR" * 8,
        "gh" + "p_" + "a1B2c3D4e5" * 4,
        "xox" + "b-1234567890-1234567890-" + "AbCdEfGhIjKl",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
    ]
    for key in keys:
        assert blanked(f"the key {key} works") == "the key [key] works", key
    assert blanked("api_key = 'abcd1234efgh5678'") == "api_key = '[key]'"
    assert blanked("Authorization: Bearer abcDEF123456ghiJKL789") == "Authorization: Bearer [key]"
    assert blanked(f"token {RANDOM} here") == "token [key] here"  # long and random
    reset = f"https://example.com/reset?token={RANDOM}&x=1"
    assert blanked(reset) == "https://example.com/reset?token=[key]&x=1"
    pem = (
        "-----BEGIN RSA PRIVATE"
        + " KEY-----\nMIIEow"
        + "Ab3" * 30
        + "\n-----END RSA PRIVATE KEY-----"
    )
    assert blanked(f"{pem}\nthanks") == "[private key]\nthanks"
    # A key labelled a password is blanked once, as a key.
    assert redact(f"password: {keys[0]}") == ("password: [key]", {"key": 1})


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("password: hunter2!", "password: [password]"),
        ("My password is Tr0ub4dor&3.", "My password is [password]."),
        ("wifi password is sunflower22", "wifi password is [password]"),
        ("Wi-Fi password: sunflower", "Wi-Fi password: [password]"),
        ("pwd=s3cr3t-pass", "pwd=[password]"),
        ('{"password": "hunter22"}', '{"password": "[password]"}'),
    ],
)
def test_passwords_are_blanked_where_one_is_said(text, shown):
    assert blanked(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("IBAN DE89 3704 0044 0532 0130 00, thanks", "IBAN [IBAN], thanks"),
        ("GB82WEST12345698765432", "[IBAN]"),
        ("BE68 5390 0754 7034 THEN", "[IBAN] THEN"),  # the word after isn't part of it
        ("account number 123456789", "account number [account number]"),
        ("Acct #: 0012-3456-789", "Acct #: [account number]"),
        ("Account No. 12345678, routing", "Account No. [account number], routing"),
    ],
)
def test_ibans_and_bank_account_numbers_are_blanked(text, shown):
    assert blanked(text) == shown


@pytest.mark.parametrize(
    "text",
    [
        # What drafts need: prices, dates, times, phone, street and order numbers.
        "Your order #112-4839201-1234567 ships 11/03/2026 for $1,234.56.",
        "Order number 1234567890123 and tracking 9400111899223344556677 are on the way.",
        "Call me at 603-555-0142, (603) 555-0199, +1 603 555 0142 or +49 1512 3456 7890.",
        "Meet at 10:30 on 2026-11-01 at 1234 Elm Street, zip code 03755.",
        "2026-11-01 2026-11-02 and 20261101123045, 603-555-0142 603-555-0199",
        "ISBN 978-0-306-40615-7; Meeting ID: 845 1234 5678; Room 4111, floor 3",
        "Total: $4,111.11; invoice INV-2026-000123; ref 000-00-0000",
        # Card-shaped, but not a card: the check fails, or it's an id in a link.
        "4111 1111 1111 1112 is off by one; 1234 5678 9012 3456 starts like no card",
        "https://x.example/status/4177198342314393712 and /orders/4111111111111111",
        # Codes that aren't one-time codes, and words that only sound like a secret.
        "the code is on GitHub; zip code: 03755; area code 603; promo code SAVE20",
        "Your Zip Code: 03755; 03755 is your zip code; Your Gift Card Code: 12345678",
        "your code review is due 11/05; Your code is ready; PIN number; pinned it",
        "Flight confirmation code: ABC123; Your confirmation code is 482913",
        "the password is incorrect; password is required; Secret Santa 2026",
        "The token is in the drawer; secret: the party is Friday",
        "account balance $1,234; account number ending in 1234",
        # Code that names a password rather than says one.
        "password = os.getcwd(); password = user_password; password=None; pwd = args.pwd",
        "password: Optional[str] = None",
        # Long names, hashes and ids, which aren't random the way a key is.
        "sha 4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39 uuid 123e4567-e89b-12d3-a456-426614174000",
        "https://docs.example.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit",
        "getUserProfileByEmailAddressAndPhoneNumber2 ThisIsAVeryLongVariableNameForTesting2026",
        "IMG20261101123456ProcessedHDRv2Final.jpg and MyBackup20261101FinalVersion2026Copy",
        "sk-learn-contrib-imbalanced-learn and risk-assessment-for-the-new-project",
        "<untrusted-1a2b3c4d>hi</untrusted-1a2b3c4d>",
    ],
)
def test_what_drafts_need_stays(text):
    assert redact(text) == (text, {})


def test_counts_are_by_kind_and_kept_values_stay():
    text = (
        "Card 4111 1111 1111 1111, SSN 123-45-6789, your code is 482913, password: hunter2!, "
        "account number 12345678 and IBAN GB82WEST12345698765432."
    )
    out, counts = redact(text)
    assert counts == {"card": 1, "ssn": 1, "code": 1, "password": 1, "account": 1, "iban": 1}
    for secret in ("4111", "6789", "482913", "hunter2", "12345678", "GB82"):
        assert secret not in out
    assert redact("account number: 1234 5678", keep=["12345678"]) == (
        "account number: 1234 5678",
        {},
    )
    assert redact("", keep=["x"]) == ("", {})


def test_a_long_prompt_is_quick():
    text = (
        "Hi Ana, the order 112-4839201-1234567 is $1,234.56, call 603-555-0142 at 10:30. "
        f"Your verification code is 482913. Card 4111 1111 1111 1111. token {RANDOM}\n"
    ) * 5000  # about 900,000 characters
    began = time.monotonic()
    out, counts = redact(text)
    assert time.monotonic() - began < 5  # well under a second here
    assert counts == {"code": 5000, "card": 5000, "key": 5000}
    assert out.count("603-555-0142") == 5000
