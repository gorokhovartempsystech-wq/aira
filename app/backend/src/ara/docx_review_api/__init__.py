"""Optional review HTTP routes; explicit analysis installation owns runtime resources."""


def install_review(app):
    from ._http import install

    install(app)
