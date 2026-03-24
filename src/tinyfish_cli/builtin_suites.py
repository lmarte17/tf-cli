from __future__ import annotations

from typing import Any, Dict


BUILTIN_SUITES: Dict[str, Dict[str, Any]] = {
    "common-web": {
        "name": "common-web",
        "description": "Live TinyFish smoke suite for common browser automation workflows.",
        "scenarios": [
            {
                "id": "multi-page-research",
                "description": "Navigate across multiple catalogue pages and open detail pages to extract structured data.",
                "request": {
                    "url": "https://books.toscrape.com/",
                    "goal": (
                        "Use the Books to Scrape sandbox. Visit page 1 of the catalogue and then navigate to page 2. "
                        "On each of page 1 and page 2, open the first book's detail page and extract the title, price, "
                        "availability, and the detail page URL from the detail page itself. Return JSON only in this exact shape: "
                        "{\"pages_visited\":[1,2],\"used_detail_pages\":true,\"items\":["
                        "{\"page\":1,\"title\":\"...\",\"detail_url\":\"...\",\"price\":\"...\",\"availability\":\"...\"},"
                        "{\"page\":2,\"title\":\"...\",\"detail_url\":\"...\",\"price\":\"...\",\"availability\":\"...\"}"
                        "]}. Do not include markdown or prose."
                    ),
                    "browser_profile": "lite",
                    "api_integration": "tinyfish-cli-suite",
                },
                "assertions": [
                    {"type": "equals", "path": "status", "value": "COMPLETED"},
                    {"type": "contains_all", "path": "result.pages_visited", "value": [1, 2]},
                    {"type": "truthy", "path": "result.used_detail_pages"},
                    {"type": "min_items", "path": "result.items", "value": 2},
                    {
                        "type": "all_items_have_keys",
                        "path": "result.items",
                        "keys": ["page", "title", "detail_url", "price", "availability"],
                    },
                ],
            },
            {
                "id": "cart-addition",
                "description": "Log in to a demo storefront, add multiple items to the cart, and confirm the cart state.",
                "request": {
                    "url": "https://www.saucedemo.com/",
                    "goal": (
                        "Use Sauce Demo. Log in with username \"standard_user\" and password \"secret_sauce\". "
                        "Add \"Sauce Labs Backpack\" and \"Sauce Labs Bike Light\" to the cart, then open the cart page. "
                        "Do not start checkout. Return JSON only in this exact shape: "
                        "{\"logged_in\":true,\"requested_items\":[\"Sauce Labs Backpack\",\"Sauce Labs Bike Light\"],"
                        "\"cart_items\":[\"...\"],\"cart_count\":2,\"cart_contains_all_requested\":true}. "
                        "Do not include markdown or prose."
                    ),
                    "browser_profile": "lite",
                    "api_integration": "tinyfish-cli-suite",
                },
                "assertions": [
                    {"type": "equals", "path": "status", "value": "COMPLETED"},
                    {"type": "truthy", "path": "result.logged_in"},
                    {"type": "equals", "path": "result.cart_count", "value": 2},
                    {"type": "truthy", "path": "result.cart_contains_all_requested"},
                    {"type": "min_items", "path": "result.cart_items", "value": 2},
                    {
                        "type": "contains_all",
                        "path": "result.requested_items",
                        "value": ["Sauce Labs Backpack", "Sauce Labs Bike Light"],
                    },
                ],
            },
            {
                "id": "form-fill-submit",
                "description": "Fill a public demo form, submit it, and confirm the result page state.",
                "request": {
                    "url": "https://www.selenium.dev/selenium/web/web-form.html",
                    "goal": (
                        "Use the Selenium demo web form. Fill the text input with \"TinyFish CLI Test\", "
                        "fill the password input with \"test-password\", select \"Two\" from the dropdown, "
                        "leave the checked checkbox enabled, keep the default radio selected, set the date field to \"04/15/2026\", "
                        "submit the form, and then inspect the destination page. Return JSON only in this exact shape: "
                        "{\"submitted\":true,\"text_input_value\":\"TinyFish CLI Test\",\"dropdown_value\":\"Two\","
                        "\"confirmation_heading\":\"...\",\"confirmation_message\":\"...\"}. "
                        "Do not include markdown or prose."
                    ),
                    "browser_profile": "lite",
                    "api_integration": "tinyfish-cli-suite",
                },
                "assertions": [
                    {"type": "equals", "path": "status", "value": "COMPLETED"},
                    {"type": "truthy", "path": "result.submitted"},
                    {"type": "equals", "path": "result.text_input_value", "value": "TinyFish CLI Test"},
                    {"type": "equals", "path": "result.dropdown_value", "value": "Two"},
                    {"type": "contains", "path": "result.confirmation_heading", "value": "Form submitted"},
                    {"type": "contains", "path": "result.confirmation_message", "value": "Received"},
                ],
            },
        ],
    }
}
