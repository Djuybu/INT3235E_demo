from bs4 import BeautifulSoup
import requests
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

#define lists of standardized keys
ORIGIN = ['nguyên quán', 'quê quán', 'nơi sinh']
MEMBERS = ['thành viên', 'thành viên hiện tại', 'thành viên chính thức']
PAST_MEMBERS = ['cựu thành viên', 'thành viên trước đây']
GENRES = ['thể loại', 'thể loại âm nhạc', 'phong cách âm nhạc']
PUBLISHERS = ['hãng đĩa']
AWARDS = ['giải thưởng']

def remove_characters(text):
    if isinstance(text, str):
        # Bỏ cụm [sửa|sửa mã nguồn]
        cleaned = text.replace("[sửa|sửa mã nguồn]", "")
        # Xoá ngoặc và dấu cách/dấu ngoặc kép ở đầu & cuối
        cleaned = re.sub(r'^[\s\(\)\[\]\'"]+|[\s\(\)\[\]\'"]+$', '', cleaned)
        return cleaned.strip()
    return text

def get_years_from_string(string):
    # Extract years from a string using regex
    return re.findall(r'\b(19|20)\d{2}\b', string)

def get_years(active_years):
    is_active = False
    if not active_years:
        return None, None

    if isinstance(active_years, str):
        active_years = [active_years]

    start_years = []
    end_years = []

    for period in active_years:
        if not period:
            continue
        p = period.strip()

        # Chuẩn hoá các loại dash thành hyphen thường
        p = re.sub(r'[–—−]', '-', p)

        # 🔹 Lấy tất cả năm và cả từ "nay"
        tokens = re.findall(r'\b(?:19|20)\d{2}\b|\b(?:nay|hiện tại|present|now)\b', p, re.IGNORECASE)

        # Nếu không có token nào, thử kiểm tra dạng đặc biệt "2015-"
        if not tokens:
            if re.search(r'\b(?:19|20)\d{2}\b\s*-\s*$', p):
                start = int(re.search(r'(?:19|20)\d{2}', p).group())
                start_years.append(start)
            continue

        # Xử lý token đầu tiên (năm bắt đầu)
        first = tokens[0]
        if re.match(r'(?:19|20)\d{2}', first):
            start_years.append(int(first))

        # Xử lý token cuối cùng (năm tan rã)
        last = tokens[-1]
        if re.match(r'(?:19|20)\d{2}', last):
            end_years.append(int(last))
        elif re.match(r'(nay|hiện tại|present|now)', last, re.IGNORECASE):
            is_active = True
            # nếu là 'nay' thì không có năm tan rã
            pass
        elif len(tokens) == 1:
            # chỉ có một năm, coi là hoạt động trong năm đó
            end_years.append(int(first))

    if not start_years:
        return None, None

    start = min(start_years)
    end = None if is_active else max(end_years)
    return start, end

def extract_tabletype_details(content):
    details = {}

    if content is None:
        return details

    # Duyệt qua từng <li> trong ul
    for li in content.find_all("li"):
        text = li.get_text(strip=True)

        # Kiểm tra xem có dấu ':' hay không
        if ":" in text:
            key, value = text.split(":", 1)  # tách 1 lần đầu tiên
            details[key.strip()] = value.strip()

    # print("Extracted details:", details)

    return details

def extract_singles(tbody):
    """
    Trích xuất thông tin các đĩa đơn từ tbody của bảng
    """
    # print("Extracting...")
    songs = []
    rows = tbody.find_all('tr')[1:]  # Bỏ qua hàng tiêu đề
    
    current_year = None
    current_album = None
    current_year_span = 0
    current_album_span = 0
    
    for row in rows:
        count = 0
        tds_row = None
        if current_year_span == 0 or current_year == None:
            count += 1
        if current_album_span == 0 or current_album == None:
            count += 1
        if count == 2:
            tds_row = row.find_all('td')
        if count == 1:
            tds_row = row.find('td')
        # Kiểm tra xem có cột năm không
        if current_year_span == 0 or current_year == None:
            year_cell = tds_row[0] if count == 2 else tds_row
            if year_cell:
                year_text = year_cell.get_text(strip=True)
                if year_text.isdigit():
                    current_year = int(year_text)
                    if year_cell.has_attr('rowspan'):
                        current_year_span = int(year_cell['rowspan']) - 1
                    else:
                        current_year_span = 0
                else:
                    current_year = None
            else:
                current_year = None
        
        else:
            current_year_span -= 1

        if current_album_span == 0 or current_album == None:
            album_cell = tds_row[1] if count == 2 else tds_row
            if album_cell:
                album_text = album_cell.get_text(strip=True)
                current_album = album_text if album_text else None
                if album_cell.has_attr('rowspan'):
                    current_album_span = int(album_cell['rowspan']) - 1
                else:
                    current_album_span = 0
            else:
                current_album = None
        else:
            current_album_span -= 1
        
        # Tìm cột title (luôn là <th scope="row">)
        title_cell = row.find('th', scope='row')
        if title_cell:
            title = title_cell.get_text(strip=True)
            
            # Kiểm tra xem có cột album không
           
            
            songs.append({
                'type': 'Đĩa đơn',
                'năm': current_year,
                'tiêu đề': title,
                'album': current_album
            })

    # print(songs)
    
    return songs

def crawl_band_albums(soup):
    albums = []

    for title_tag in soup.select("div.mw-heading.mw-heading2"):
        text = remove_characters(title_tag.get_text(strip=True)).lower()
        print(f"Found heading2: {text}")
        if "album" in text or "đĩa nhạc" in text:
            album_type = "Album"
            # Duyệt các thẻ anh em sau tiêu đề chính
            for sib in title_tag.find_next_siblings():
                # Nếu gặp tiêu đề cấp 2 khác => dừng
                if sib.name == "div" and "mw-heading2" in sib.get("class", []):
                    # print("Encountered another level 2 heading, stopping.")
                    break

                # Nếu là tiêu đề cấp 3 => loại album (studio, live, v.v.)
                if sib.name == "div" and "mw-heading3" in sib.get("class", []):
                    album_type = remove_characters(sib.get_text(strip=True))
                    # print(f"Processing album type: {album_type}")


                if 'Đĩa đơn' in sib.get_text(strip=True):
                    # print("Processing 'Đĩa đơn' section")
                    tbody = sib.find('tbody')
                    if tbody:
                        albums.extend(extract_singles(tbody))
                    break


                # Nếu gặp bảng album
                if sib.name == "table":
                    headers = [th.get_text(strip=True).lower() for th in sib.find_all("th")]
                    if len(headers) == 4 and album_col is not None:
                        album_col = None
                        release_col = None
                        for i, h in enumerate(headers):
                            if "album" in h:
                                album_col = i
                            elif "phát hành" in h:
                                release_col = i
                        for row in rows:
                            cells = row.find_all(["td", "th"])
                            if not cells:
                                continue
                            album["title"] = cells[album_col].get_text(strip=True) if album_col < len(cells) else None
                            album["release_date"] = cells[release_col].get_text(strip=True) if release_col is not None and release_col < len(cells) else None
                    else:
                        rows = sib.find_all("tr")[1:]  # bỏ hàng tiêu đề
                        for row in rows:
                            print("Processing album row")
                            album = {}
                            album["type"] = album_type
                            th = row.find("th")
                            td = row.find("td")

                            # Nội dung chi tiết trong <ul>
                            ul_tag = td.find("ul") if td else None
                            # print(extract_tabletype_details(ul_tag))
                            album.update(extract_tabletype_details(ul_tag))
                            album['title'] = th.get_text(strip=True) if th else None
                        # print(f"Album title: {album['title']}")
                        for key in album:
                            if album[key]:
                                album[key] = remove_characters(album[key])
                        albums.append(album)
                
                elif sib.name == "ul":
                    print("Processing <ul> list of albums")
                    for li in sib.find_all("li"):
                        text = li.get_text(strip=True)
                        match = re.match(r'^(.*?)\s*\((\d{4})\)$', text)
                        if match:
                            title, year = match.groups()
                            album = {"type": album_type,"title": title.strip(), "year": int(year)}
                            for key in album:
                                if album[key]:
                                    print(album[key])
                                    album[key] = remove_characters(album[key])
                            albums.append(album)
                                
    return albums

# Hàm crawl các trang Web trong phần danh mục
def crawl_category_website(url):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Check if the request was successful
        soup = BeautifulSoup(response.text, 'html.parser')

        # Trỏ vào phần chứa các url
        singer_links = soup.find("div", {"id": "mw-pages"})

        # Lấy tất cả các thẻ <a> trong phần này
        links = singer_links.find_all('a', href=True)
        urls = ["https://vi.wikipedia.org" + link['href'] for link in links if link['href'].startswith('/wiki/')]
        return urls

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []
    
def crawl_singer_info(urls):
    singers = []
    for url in urls:
        try:
            print(f"Crawling {url}...")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            #Trỏ vào info box
            info_box = soup.find("table", {"class": "infobox"})
            if not info_box:
                continue
            info_rows = info_box.find_all("tr")
            singer_info = {}
            singer_info['name'] = soup.find("h1", {"id": "firstHeading"}).get_text(strip=True)
            for row in info_rows:
                header = row.find("th")
                data = row.find("td")
                if header and data:
                    key = header.get_text(strip=True)

                    # --- TRƯỜNG HỢP 1: Có <div class="hlist"> ---
                    hlist_div = data.find("div", {"class": "hlist"})
                    if hlist_div:
                        # Lấy nội dung trong các <li>
                        items = [li.get_text(strip=True) for li in hlist_div.find_all("li")]
                        singer_info[key] = items
                        continue  # bỏ qua các xử lý tiếp theo, vì đã có kết quả

                    ul_tag = data.find("ul")
                    if ul_tag:
                        items = [li.get_text(strip=True) for li in ul_tag.find_all("li")]
                        singer_info[key] = items
                        continue

                    # --- TRƯỜNG HỢP 2: Có <br> ---
                    if data.find("br"):
                        # split dựa theo thẻ <br>
                        parts = [text.strip() for text in data.stripped_strings]
                        singer_info[key] = [p for p in parts if p]  # loại bỏ chuỗi rỗng
                    else:
                        # Trường hợp bình thường
                        value = data.get_text(separator=' ', strip=True)
                        singer_info[key] = value
                    
                    singer_info['năm thành lập'], singer_info['năm tan rã'] = get_years(singer_info.get('Năm hoạt động'))
            # print(f"Singer Info from {url}: {singer_info}")
            singer_info['albums'] = crawl_band_albums(soup)
            singers.append(singer_info)
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
    return singers

def beautify_data(singers):
    # print(type(singers))
    for singer in singers:
        # print(singer)
        if 'Nguyên quán' in singer and "Sài Gòn" in singer.get('Nguyên quán'):
            singer['Nguyên quán'] = 'TP.Hồ Chí Minh, Việt Nam'
        if not singer.get('Hãng đĩa'):
            singer['Hãng đĩa'] = 'Độc lập'
        if isinstance(singer.get('Thành viên'), list):
            for member in singer['Thành viên']:
                if member in ['Xem lịch sử thành viên', 'Xem Thành viên', 'Xem lịch sử nhân sự']:
                    singer['Thành viên'].remove(member)
        elif isinstance(singer.get('Thành viên'), str):
            if singer['Thành viên'] in ['Xem lịch sử thành viên', 'Xem Thành viên', 'Xem lịch sử nhân sự']:
                singer['Thành viên'] = None
        if "ban nhạc" in singer.get('name'):
            singer['name'] = re.sub(r"\(ban nhạc\)", "", singer['name'], flags=re.IGNORECASE).strip()
    return singers

def export_to_json(singers, filename='singers.json'):
    import json
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(singers, f, ensure_ascii=False, indent=4)

urls = crawl_category_website("https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Ban_nh%E1%BA%A1c_Vi%E1%BB%87t_Nam")
bands = crawl_singer_info(urls)
# print(bands)
bands = beautify_data(bands)
export_to_json(bands, 'raw_data/bands.json')
# print(crawl_band_albums(BeautifulSoup(requests.get("https://vi.wikipedia.org/wiki/C%C3%A1_H%E1%BB%93i_Hoang", headers=headers).text, 'lxml')))