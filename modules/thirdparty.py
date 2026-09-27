import sys
import json
import re
from urllib.parse import urlparse
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def get_registered_domain(url_or_netloc):
    """Extract base/registered domain from URL or hostname."""
    if not url_or_netloc:
        return ""
    if "://" not in url_or_netloc:
        url_or_netloc = "http://" + url_or_netloc
    netloc = urlparse(url_or_netloc).netloc.split(":")[0].lower()
    parts = netloc.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return netloc

def scrape_website(target_url):
    with sync_playwright() as p:
        # Launch headless browser to catch dynamically loaded scripts/DOM elements
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()

        # Track network requests as fallbacks
        network_requests = set()
        page.on("request", lambda req: network_requests.add(req.url))

        try:
            page.goto(target_url, wait_until="networkidle", timeout=15000)
        except Exception:
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
            except Exception as e:
                print(f"Navigation warning for {target_url}: {e}")

        html_content = page.content()
        browser.close()

    soup = BeautifulSoup(html_content, "lxml")
    target_domain = urlparse(target_url).netloc.split(":")[0].lower()
    target_registered_domain = get_registered_domain(target_url)

    # ------------------ Extract DOM Elements ------------------ #
    
    # 1. Scripts
    all_scripts = [tag.get("src") for tag in soup.find_all("script") if tag.get("src")]
    
    # 2. Stylesheets & Fonts
    all_stylesheets = [tag.get("href") for tag in soup.find_all("link", rel=lambda r: r and "stylesheet" in r.lower()) if tag.get("href")]
    all_fonts = [tag.get("href") for tag in soup.find_all("link", rel=lambda r: r and "font" in r.lower()) if tag.get("href")]

    # 3. Iframes
    all_iframes = [tag.get("src") for tag in soup.find_all("iframe") if tag.get("src")]

    # 4. Images
    all_images = [tag.get("src") for tag in soup.find_all("img") if tag.get("src")]

    # 5. Links
    all_links = [tag.get("href") for tag in soup.find_all("a") if tag.get("href")]

    # 6. Media (Audio/Video/Source tags)
    all_media = []
    for tag in soup.find_all(["video", "audio", "source"]):
        src = tag.get("src")
        if src:
            all_media.append(src)

    # Helper function to check third-party status
    def is_external(resource_url):
        if not resource_url or resource_url.startswith("data:") or resource_url.startswith("#"):
            return False
        parsed = urlparse(resource_url)
        if not parsed.netloc:
            return False  # Relative path = internal
        res_domain = get_registered_domain(resource_url)
        return res_domain != target_registered_domain

    # Filter external resources
    external_scripts = list(set([s for s in all_scripts if is_external(s)]))
    external_stylesheets = list(set([s for s in all_stylesheets if is_external(s)]))
    external_iframes = list(set([f for f in all_iframes if is_external(f)]))
    external_images = list(set([i for i in all_images if is_external(i)]))
    external_links = list(set([l for l in all_links if is_external(l)]))
    external_media = list(set([m for m in all_media if is_external(m)]))

    # Collect third-party domains
    third_party_domains = set()
    for res_list in [external_scripts, external_stylesheets, external_iframes, external_images, external_links, external_media]:
        for res_url in res_list:
            netloc = urlparse(res_url).netloc.split(":")[0].lower()
            if netloc:
                third_party_domains.add(netloc)

    # Identify Analytics & Advertising
    analytics_patterns = re.compile(r"(analytics|gtag|google-analytics|matomo|mixpanel|segment|pixel|doubleclick)", re.I)
    analytics_endpoints = [res for res in (external_scripts + external_links) if analytics_patterns.search(res)]

    # ------------------ Build JSON Payload ------------------ #
    json_output = {
        "url": target_url,
        "base_domain": target_domain,
        "extraction_timestamp": datetime.utcnow().isoformat(),
        "external_scripts": external_scripts,
        "external_iframes": external_iframes,
        "external_images": external_images,
        "external_stylesheets": external_stylesheets,
        "external_fonts": list(set(all_fonts)),
        "external_fonts_css": [],
        "external_media": external_media,
        "form_actions": [tag.get("action") for tag in soup.find_all("form") if tag.get("action")],
        "form_inputs": [tag.get("name") or tag.get("type") for tag in soup.find_all("input")],
        "analytics_endpoints": analytics_endpoints,
        "tracking_pixels": [img for img in external_images if "pixel" in img or "tracking" in img],
        "external_links": external_links,
        "cdn_domains": [d for d in third_party_domains if "cdn" in d or "cloudflare" in d or "fastly" in d],
        "social_media_widgets": [d for d in third_party_domains if any(s in d for s in ["facebook", "twitter", "linkedin", "instagram"])],
        "advertising_elements": [d for d in third_party_domains if any(a in d for a in ["doubleclick", "adservice", "adnxs", "googlesyndication"])],
        "javascript_frameworks": [],
        "resource_distribution": {
            "scripts": len(all_scripts),
            "stylesheets": len(all_stylesheets),
            "images": len(all_images),
            "iframes": len(all_iframes),
            "fonts": len(all_fonts),
            "links": len(all_links),
            "media": len(all_media),
            "analytics": len(analytics_endpoints),
            "total_external": len(external_scripts) + len(external_stylesheets) + len(external_iframes) + len(external_images) + len(external_links) + len(external_media),
            "total_internal": (len(all_scripts) - len(external_scripts)) + (len(all_images) - len(external_images)) + (len(all_links) - len(external_links))
        },
        "security_risks": [],
        "third_party_domains": sorted(list(third_party_domains)),
        "total_external_resources": len(external_scripts) + len(external_stylesheets) + len(external_iframes) + len(external_images) + len(external_links) + len(external_media),
        "extraction_metadata": {
            "parser_used": "Playwright + BeautifulSoup (lxml)",
            "version": "3.0",
            "extraction_method": "Headless DOM Execution & Dynamic Interception"
        }
    }

    return json_output

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://www.silverbell.000space.com/"
    data = scrape_website(url)
    with open("output.json", "w") as f:
        json.dump(data, f, indent=4)
    print("Scraping completed. JSON saved to output.json")