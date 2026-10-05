"""Debug helper: `python -m cookie [cookies.txt]` exports the Firefox cookies
without starting the app."""

import logging
import sys

from cookie.firefox import CookieExportError, export_firefox_cookies

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    target = sys.argv[1] if len(sys.argv) > 1 else "cookies.txt"
    try:
        res = export_firefox_cookies(target)
    except CookieExportError as err:
        print(f"Error: {err}")
        sys.exit(1)
    print(f"Profile : {res.profile}")
    print(f"Cookies : {res.count}")
    print(f"Signed in to Google/YouTube: {'yes' if res.logged_in else 'NO'}")
    print(f"Written : {res.path}")
