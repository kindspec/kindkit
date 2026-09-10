A fixture that is only correct as exact bytes, committed as such.

`.gitattributes` disables end-of-line normalisation for this tree; without a
CRLF fixture actually in it that rule guards nothing, and a checkout that
normalised it would go unnoticed. `test_the_committed_crlf_fixture_kept_its_crlf`
reads this file's bytes so the rule has something to protect.
