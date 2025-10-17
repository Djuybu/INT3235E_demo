import requests
from bs4 import BeautifulSoup
import json
import os

SAVE_DIR = r"C:\Users\Woangchung\INT3235E_demo\raw_data"
EXCLUDED_PATH = os.path.join(SAVE_DIR, "excluded_links.json")

def load_excluded_links():
    if os.path.exists(EXCLUDED_PATH):
        with open(EXCLUDED_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_excluded_links(excluded_links):
    with open(EXCLUDED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(excluded_links)), f, ensure_ascii=False, indent=2)

def crawl_valid_links(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Các mục heading được phép lấy link phía sau
    target_headings = [
        "Cuộc đời sự nghiệp",
        "Phong cách nghệ thuật",
        "Hình tượng công chúng",
        "Danh sách đĩa nhạc"
    ]

    valid_sections = []
    for heading in soup.find_all(['div'], class_=['mw-heading2', 'mw-heading3']):
        text = heading.get_text(strip=True)
        if text in target_headings:
            valid_sections.append(heading)

    all_links = []
    for section in valid_sections:
        for sibling in section.find_all_next():
            if sibling.name in ['div'] and 'mw-heading' in ' '.join(sibling.get('class', [])):
                break  # Dừng khi gặp heading khác
            links = sibling.find_all('a', href=True)
            for link in links:
                href = link['href']
                if href.startswith('/wiki/') and not any(x in href for x in [':', '#']):
                    full_url = "https://vi.wikipedia.org" + href
                    all_links.append(full_url)

    all_links = list(dict.fromkeys(all_links))
    print(f"🔍 Tìm thấy {len(all_links)} đường dẫn sau các mục yêu cầu.")

    excluded_links = load_excluded_links()
    print(f"📂 Đang bỏ qua {len(excluded_links)} link đã bị loại trước đó...")

    valid_links = []
    new_excluded = set()
    keywords = ["ca sĩ Việt Nam", "nam ca sĩ Việt Nam", "nữ ca sĩ Việt Nam"]

    for link in all_links:
        if link in excluded_links:
            print(f"⏩ Bỏ qua (đã loại trước): {link}")
            continue

        try:
            sub_resp = requests.get(link, headers=headers, timeout=5)
            sub_soup = BeautifulSoup(sub_resp.text, 'html.parser')
            cat_div = sub_soup.find('div', id='mw-normal-catlinks')

            if cat_div and any(k in cat_div.get_text() for k in keywords):
                valid_links.append(link)
                print(f"✅ Giữ lại: {link}")
            else:
                print(f"❌ Loại bỏ: {link}")
                new_excluded.add(link)

        except Exception as e:
            print(f"⚠️ Lỗi khi truy cập {link}: {e}")
            new_excluded.add(link)

    excluded_links.update(new_excluded)
    save_excluded_links(excluded_links)

    return valid_links


if __name__ == "__main__":
    os.makedirs(SAVE_DIR, exist_ok=True)

    url = input("🔗 Nhập URL Wikipedia: ").strip()
    name = input("📁 Đặt tên file JSON (ví dụ: male, female, band...): ").strip()
    save_file = os.path.join(SAVE_DIR, f"singers_{name}.json")

    links = crawl_valid_links(url)

    with open(save_file, "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Đã lưu {len(links)} đường dẫn hợp lệ vào: {save_file}")
    print(f"📁 Danh sách link loại bỏ được lưu tại: {EXCLUDED_PATH}")
