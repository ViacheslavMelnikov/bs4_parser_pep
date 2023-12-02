import re
from urllib.parse import urljoin
import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm
import logging
from constants import BASE_DIR, MAIN_DOC_URL, PEPS_DOC_URL, EXPECTED_STATUS
from utils import get_response, find_tag
from configs import configure_argument_parser, configure_logging
from outputs import control_output


def whats_new(session) -> list:
    results = [("Ссылка на статью", "Заголовок", "Редактор, Автор")]
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return results
    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'})

    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        version_link = urljoin(whats_new_url, version_a_tag['href'])
        response = get_response(session, version_link)
        if response is None:
            continue

        soup = BeautifulSoup(response.text, 'lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )

    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise Exception('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''

        results.append(
            (link, version, status)
        )

    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})
    pdf_a4_tag = find_tag(
        table_tag, 'a', {'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    response = get_response(session, PEPS_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    data = {}
    sum_status = {
        'Active': 0,
        'Accepted': 0,
        'Deferred': 0,
        'Draft': 0,
        'Final': 0,
        'Provisional': 0,
        'Rejected': 0,
        'Superseded': 0,
        'Withdrawn': 0,
    }
    tables = soup.find_all(
        'table', class_='pep-zero-table docutils align-default')
    for table in tqdm(tables, "Общий процент выполнения", leave=False):
        table_body = table.find('tbody')
        rows = table_body.find_all('tr')
        for row in tqdm(rows, "Обработка текущей таблицы", leave=False):
            cols = row.find_all('td')
            preview_status = cols[0].text[1:]
            href_pep = cols[1].find('a')
            link_pep_info = urljoin(PEPS_DOC_URL, href_pep['href'])

            response_pep = get_response(session, link_pep_info)
            if response_pep is None:
                return
            soup_pep = BeautifulSoup(response_pep.text, features='lxml')
            status_pep = soup_pep.find(
                string="Status").parent.find_next_sibling().text
            data[link_pep_info] = (preview_status, status_pep)

    rezult_non = []
    for row in data:
        preview_status, status_pep = data[row]
        if status_pep in EXPECTED_STATUS[preview_status]:
            sum_status[status_pep] += 1
        else:
            rezult_non.append([link_pep_info, preview_status, status_pep])

    if len(rezult_non) > 0:
        log_pep = "\n" + "Несовпадающие статусы:"
        for link_pep, preview_pep, status_pep in rezult_non:
            expected_statuses = list(EXPECTED_STATUS[preview_pep])
            log_pep += "\n" + link_pep
            log_pep += "\n" + f"Статус в карточке: {status_pep}"
            log_pep += "\n" + f"Ожидаемые статусы: {expected_statuses}"
        logging.info(log_pep)

    results = []
    total = 0
    for s in sum_status:
        total += sum_status[s]
        results.append([s, sum_status[s]])
    results.append(["Total", total])
    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
