# ============================================================
# Test data for the Language Configuration screen.
# Converted from the source suite; the target language now comes
# from the profile.
# ============================================================

from backoffice.utils import randoms


def generate_language_translation_data(profile):
    """A unique source/target word pair for one Language Configuration save.

    Both fixed target languages (Bangla, Arabic) already have a
    language-pair record in every environment, so saving always replaces
    that pair's single translation row rather than adding a new pair -
    which is why the app answers "Successfully Edited" and not
    "Successfully Created". That is expected, not a defect; see
    LanguageConfigurationPage.success_notification.

    The random suffix is what makes the replaced value identifiable as
    this run's.
    """
    suffix = randoms.digits(6)

    return {
        "targetLanguage": profile.data("language", "target"),
        "sourceValue": "AutoSourceWord_" + suffix,
        "targetValue": "AutoTargetWord_" + suffix,
    }
