"""B2 relevance regressions; captured excerpts are labelled at their definitions.

The real filter is exercised. A rejecting provider boundary is an explicit
negative control, not a model response or a relevance-quality evaluation.
"""
import asyncio

import pytest

from behive.engine.process import RelevanceFilter

TOPIC = 'Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta, cennik, wdrożenia'


@pytest.fixture
def rejecting_relevance(monkeypatch):
    seen = []

    async def reject_unknown(self, docs):
        seen.extend(d['url'] for d in docs)
        return [0.0] * len(docs)

    monkeypatch.setattr(RelevanceFilter, 'score_batch', reject_unknown)
    return seen


@pytest.mark.parametrize('source_id', [
    73401, 73354, 73391, 73430, 73392, 73393, 73416, 73397, 73398, 73383,
])
def test_captured_previous_selection_is_not_auto_passed_as_topic_evidence(source_id, rejecting_relevance):
    doc = dict(CAPTURED[source_id])
    assert asyncio.run(RelevanceFilter(TOPIC).filter([doc])) == []


@pytest.mark.parametrize('source_id', [73350, 73359])
def test_captured_english_wms_pages_match_polish_topic_without_a_model(source_id, monkeypatch):
    async def no_model(self, docs):
        pytest.fail('An explicit warehouse-management expansion is strong keyword evidence')
    monkeypatch.setattr(RelevanceFilter, 'score_batch', no_model)
    doc = dict(CAPTURED[source_id])
    assert asyncio.run(RelevanceFilter(TOPIC).filter([doc])) == [doc]


@pytest.mark.parametrize('text', [
    'body { font-family: system-ui; color:rgba(0,0,0,1); } ' * 5,
    '<script>var x = "systemy informatyczne";</script><style>.wms{color:red}</style>',
    '```javascript\nfunction fake(){return "systemy informatyczne";}\n```',
    'var fake = "systemy informatyczne"; ' * 5,
    '<!-- systemy informatyczne -->' * 5,
])
def test_code_and_markup_tokens_do_not_auto_pass(text, rejecting_relevance):
    doc = {'url': 'https://offline.example.test/code', 'raw_text': text}
    assert asyncio.run(RelevanceFilter('Systemy informatyczne WMS').filter([doc])) == []


@pytest.mark.parametrize('text', [
    'System działa poprawnie, ale nie opisuje działalności dostawców. ' * 4,
    'Oferta uniwersytetu obejmuje kierunki studiów i wsparcie studentów. ' * 4,
    'Wms Recykling świadczy usługi wywozu odpadów komunalnych. ' * 4,
    'System działa.',
])
def test_single_generic_or_ambiguous_token_requires_model_review(text, rejecting_relevance):
    doc = {'url': 'https://offline.example.test/ambiguous', 'raw_text': text}
    assert asyncio.run(RelevanceFilter(TOPIC).filter([doc])) == []


@pytest.mark.parametrize('topic,text', [
    ('Telemetrii zbiorników', 'Telemetria zbiornika ułatwia pomiar poziomu cieczy.'),
    ('Wdrożenia cennik', 'Wdrożenie zakończono; cenniki usług są dostępne.'),
    ('ERP telemetrii', 'ERP integrates telemetry for monitoring tank levels.'),
])
@pytest.mark.parametrize('field', ['content', 'text', 'raw_text'])
def test_meaningful_inflections_work_in_all_supported_content_fields(topic, text, field, rejecting_relevance):
    doc = {'url': 'https://offline.example.test/inflections', field: text * 4}
    assert asyncio.run(RelevanceFilter(topic).filter([doc])) == [doc]


def test_model_review_receives_readable_excerpt_not_legacy_css(monkeypatch):
    # Explicit negative provider-boundary control; no model is contacted.
    from behive.engine import process
    prompts = []
    def reject(prompt, *args):
        prompts.append(prompt)
        return '[0.0]'
    monkeypatch.setattr(process._sglang, 'is_available', lambda: True)
    monkeypatch.setattr(process._sglang, 'invoke', reject)
    doc = dict(CAPTURED[73397])
    original = doc['raw_text']
    assert asyncio.run(RelevanceFilter(TOPIC).filter([doc])) == []
    assert len(prompts) == 1
    assert 'Wms Recykling' in prompts[0]
    assert 'font-family' not in prompts[0]
    assert 'antiClickjack' not in prompts[0]
    assert 'body{display' not in prompts[0]
    assert doc['raw_text'] == original, 'Scoring cleanup must not rewrite captured evidence'


def test_unicode_keywords_keep_polish_letters_and_split_underscores():
    # The helper is also used by legacy callers; preserve its set[str] contract.
    assert RelevanceFilter._extract_keywords('Wdrożenia systemów WMS_ERP 2026') == {
        'wdrożenia', 'systemów', 'wms', 'erp', '2026'}


def test_polish_english_inflections_survive_the_real_keyword_filter(monkeypatch):
    doc = {'url': 'https://offline.example.test/telemetry', 'title': 'Telemetry zbiornika',
           'raw_text': ('Telemetry zbiornika pozwala odczytać poziom cieczy. '
                        'Operator otrzymuje aktualny pomiar i historię wskazań. ' * 3)}
    async def reject_unknown(self, docs):
        return [0.0] * len(docs)
    monkeypatch.setattr(RelevanceFilter, 'score_batch', reject_unknown)
    assert asyncio.run(RelevanceFilter('Telemetrii zbiorników').filter([doc])) == [doc]


# Captured from B/mission_snapshot.json, mission hive_1792672143_a6ba24.
# Each raw_text is an exact first-2200-character excerpt except:
# 73401 stops before challenge tokens; 73359 joins [0:650] and [18800:20400]
# to retain the leading script and the actual English WMS title/prose.
# No original HTML or positive model response was captured here.
CAPTURED = {73350: {'raw_text': 'Warehouse management software market share worldwide 2026 | Statista '
                     '{"@context":"https://***@type":"WebPage","name":"Warehouse management '
                     'software market share worldwide 2026","description":"In 2026, Knapp was the '
                     'leading vendor of the global warehouse management software market, with a '
                     '***** percent market share. The source specifies that warehouse management '
                     'software assists in managing the operations of a warehouse or distribution '
                     'center.","url":"https://www.statista.com/statistics/503241/worldwide-data-warehouse-management-software-market-share/","isAccessibleForFree":false,"breadcrumb":{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"item":{"@id":"https://www.statista.com/markets/418/technology-telecommunications/","name":"Technology '
                     '\\u0026 '
                     'Telecommunications"}},{"@type":"ListItem","position":2,"item":{"@id":"https://www.statista.com/markets/418/topic/484/software/","name":"Software"}},{"@type":"ListItem","position":3,"item":{"@id":"https://www.statista.com/statistics/503241/worldwide-data-warehouse-management-software-market-share/","name":"Share '
                     'of warehouse management software market worldwide in 2026, by '
                     'vendor"}}]},"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,"cssSelector":".masked_value"},{"@type":"Article","datePublished":"2026-03-23T12:00:00Z","dateModified":"2026-03-23T16:24:58.657837Z","headline":"Warehouse '
                     'management software market share worldwide '
                     '2026","image":"https://cdn.statcdn.com/static/openGraph/statista.png","author":{"@type":"Organization","name":"Statista '
                     'Research '
                     'Department","url":"https://www.statista.com/aboutus/our-research-commitment/","logo":{"@type":"ImageObject","url":"https://cdn.statcdn.com/static/openGraph/statista.png"}}},{"@type":"Dataset","name":"Warehouse '
                     'management software market share worldwide 2026","description":"In 2026, '
                     'Knapp was the leading vendor of the global warehouse management software '
                     'market, with a ***** percent market share. The source specifies that '
                     'warehouse management software assists in managing the operations of a '
                     'warehouse or distribution '
                     'center.","url":"https://www.statista.com/statistics/503241/worldwide-data-warehouse-management-softwar',
         'source_id': 73350,
         'title': None,
         'url': 'https://www.statista.com/statistics/503241/worldwide-data-warehouse-management-software-market-share/'},
 73354: {'raw_text': 'Prace serwisowe - UAM body, html { height: 100%; margin: 0; font-family: '
                     "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f9f9f9; "
                     'color: #333; display: flex; justify-content: center; align-items: center; '
                     'text-align: center; } .container { padding: 20px; max-width: 600px; } .logo '
                     '{ max-width: 250px; height: auto; margin-bottom: 30px; animation: fadeIn '
                     '1.5s ease-in-out; } h1 { font-size: 1.8rem; font-weight: 400; margin-bottom: '
                     '15px; color: #000; } p { font-size: 1.1rem; color: #666; line-height: 1.6; } '
                     '@keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { '
                     'opacity: 1; transform: translateY(0); } } .footer { position: absolute; '
                     'bottom: 20px; font-size: 0.8rem; color: #aaa; } Informujemy, że w związku z '
                     'informacjami o krytycznych podatnościach bezpieczeństwa w oprogramowaniu '
                     'PHP, które mogą dotyczyć części udostępnianych przez nas usług '
                     'internetowych, zdecydowaliśmy o czasowym, prewencyjnym ograniczeniu dostępu '
                     'do usług WWW. Decyzja jest podyktowana koniecznością ograniczenia '
                     'potencjalnego ryzyka do czasu wyjaśnienia charakteru zagrożeń, oceny ich '
                     'wpływu na nasze systemy oraz ewentualnego wdrożenia odpowiednich '
                     'aktualizacji bezpieczeństwa. Podkreślamy, że ograniczenie dostępu nie jest '
                     'wynikiem stwierdzenia naruszenia bezpieczeństwa naszych systemów. Jest to '
                     'działanie zapobiegawcze, mające na celu ochronę infrastruktury i danych '
                     'użytkowników. &copy; 2026 Uniwersytet im. Adama Mickiewicza w Poznaniu',
         'source_id': 73354,
         'title': None,
         'url': 'https://pressto.amu.edu.pl/index.php/se/article/view/21232'},
 73359: {'raw_text': '(self.__next_s=self.__next_s||[]).push([0,{"children":"\\nwindow.addEventListener(\'CookiebotOnConsentReady\', '
                     'function (event) {\\n var csrfCookie = document.cookie.split(\\";\\")\\n '
                     '.map(function(cookie) { return cookie.trim() })\\n .filter(function(cookie) '
                     '{ return cookie.startsWith(\\"CSRF-TOKEN=\\") })\\n .map(function(cookie) { '
                     'return cookie.split(\\"=\\")[1] })\\n .join(\\"\\");\\n\\n '
                     "fetch('https://issuu.com/api/user-service/public.user.consent.setProfilingConsent', "
                     "{\\n method: 'POST',\\n headers: {\\n 'Content-Type': 'application/json',\\n "
                     '\'X-CSRF-TOKEN\': csrfCookie\\n },\\n body: JSON.stringify({ \\"json\\": '
                     '!!Cookiebot.consent.marketing })\\n });\\n});\\n"}]) es Dive into our '
                     'extensive resources on the topic that interests you. It&#x27;s like a '
                     'masterclass to be explored at your own pace. Pricing Log in Sign up '
                     '{"@context":"https://schema.org","@type":"DigitalDocument","name":"Warehouse '
                     'Management System Market Future Scope 2025","description":"Browse Complete '
                     'Report Warehouse Management System Market 2025 for Better Understanding: '
                     'https://www.skyquestt.com/report/warehouse-management-system-market","image":"https://image.isu.pub/250519095202-633a00370e8fa71f4f384fc8d9899de0/jpg/page_1_thumb_large.jpg","datePublished":"2025-05-19T00:00:00.000Z","inLanguage":"en","author":{"@type":"Person","name":"SkyQuest '
                     'Technology '
                     'Group","url":"https://issuu.com/skyquest-technology"},"publisher":{"@type":"Organization","name":"Issuu","url":"https://issuu.com"}} '
                     'Advertisement Advertisement Advertisement Advertisement Turn static files '
                     'into dynamic content formats. Create a flipbook Warehouse Management System '
                     'Market Future Scope 2025 Published on May 19, 2025 Report content SkyQuest '
                     'Technology Group Follow this publisher Browse Complete Report Warehouse '
                     'Management System Market 2025 for Better Understanding: '
                     'https://www.skyquestt.com/report/warehouse-management-system-market '
                     'Advertisement Read more Advertisement Advertisement Issuu converts static '
                     'files into: digital portfolios online yearbooks online catalogs digital '
                     'photo albums and more. Sign up and create your flipbook . Issuu © Bending '
                     'Spoons Operations S.p.A. Sole shareholder company subject to the management '
                     'and coordination of Bending Spoons S.p.A. Via Nino Bonnet 10, 20154, Milan, '
                     'Ital',
         'source_id': 73359,
         'title': None,
         'url': 'https://issuu.com/skyquest-technology/docs/warehouse_management_system_market_future_scope_20'},
 73383: {'raw_text': 'Poland: private health care market value 2022 | Statista '
                     '{"@context":"https://***@type":"WebPage","name":"Poland: private health care '
                     'market value 2022","description":"According to the source, it is estimated '
                     'that the value of the private healthcare market in Poland will reach over ** '
                     'billion zloty in '
                     '2022.","url":"https://www.statista.com/statistics/1239142/poland-private-health-care-market-value/","isAccessibleForFree":false,"breadcrumb":{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"item":{"@id":"https://www.statista.com/markets/412/health-pharma-medtech/","name":"Health, '
                     'Pharma \\u0026 '
                     'Medtech"}},{"@type":"ListItem","position":2,"item":{"@id":"https://www.statista.com/markets/412/topic/454/health-system/","name":"Health '
                     'System"}},{"@type":"ListItem","position":3,"item":{"@id":"https://www.statista.com/statistics/1239142/poland-private-health-care-market-value/","name":"Value '
                     'of the private healthcare market in Poland from 2019 to 2022 (in billion '
                     'zloty)"}}]},"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,"cssSelector":".masked_value"},{"@type":"Article","datePublished":"2023-07-25T12:00:00Z","dateModified":"2023-07-25T12:00:00Z","headline":"Poland: '
                     'private health care market value '
                     '2022","image":"https://cdn.statcdn.com/static/openGraph/statista.png","author":{"@type":"Organization","name":"Statista '
                     'Research '
                     'Department","url":"https://www.statista.com/aboutus/our-research-commitment/","logo":{"@type":"ImageObject","url":"https://cdn.statcdn.com/static/openGraph/statista.png"}}},{"@type":"Dataset","name":"Poland: '
                     'private health care market value 2022","description":"According to the '
                     'source, it is estimated that the value of the private healthcare market in '
                     'Poland will reach over ** billion zloty in '
                     '2022.","url":"https://www.statista.com/statistics/1239142/poland-private-health-care-market-value/","keywords":["private '
                     'health insurance","health service","healthcare services","private health '
                     'insurers","health services"],"temporalCoverage":"From 01/01/2019 to '
                     '31/12/2022","spatialCoverage":{"@type":"Place","name":"Poland"},"creator":{"@type":"Organization","name":"Statista '
                     'Research Department","url":"https:',
         'source_id': 73383,
         'title': None,
         'url': 'https://www.statista.com/statistics/1239142/poland-private-health-care-market-value/'},
 73391: {'raw_text': 'Road Freight Services Market Size | Share Analysis Report, 2035 @font-face { '
                     "font-family: 'Assistant'; font-style: normal; font-weight: 200; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 300; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Light.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Light.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 400; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 500; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 600; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 700; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Bold.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Bold.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 800; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff') format('woff'); } "
                     'body, html { font-family: "Assistant", -apple-system, BlinkMacSystemFont, '
                     '"Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica '
                     'Neue", sans-serif; } .gssb_c{ width:220px !important; right: 20px '
                     '!important; left: auto !important; } .report-body h2, .report-body h3 { '
                     'line-height: normal !important; } .css-vubbuv { -webkit-user-select: none; '
                     '-moz-user-select: none; -ms-user-select: none; user-select: none; widt',
         'source_id': 73391,
         'title': None,
         'url': 'https://www.gminsights.com/industry-analysis/road-freight-services-market'},
 73392: {'raw_text': 'Railway Management Systems Market Size, Growth Trends 2035 @font-face { '
                     "font-family: 'Assistant'; font-style: normal; font-weight: 200; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 300; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Light.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Light.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 400; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 500; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 600; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 700; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Bold.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Bold.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 800; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff') format('woff'); } "
                     'body, html { font-family: "Assistant", -apple-system, BlinkMacSystemFont, '
                     '"Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica '
                     'Neue", sans-serif; } .gssb_c{ width:220px !important; right: 20px '
                     '!important; left: auto !important; } .report-body h2, .report-body h3 { '
                     'line-height: normal !important; } .css-vubbuv { -webkit-user-select: none; '
                     '-moz-user-select: none; -ms-user-select: none; user-select: none; width: 1e',
         'source_id': 73392,
         'title': None,
         'url': 'https://www.gminsights.com/industry-analysis/railway-management-system-market'},
 73393: {'raw_text': 'Freight Brokerage Market Size &amp; Share, Growth Trends 2032 @font-face { '
                     "font-family: 'Assistant'; font-style: normal; font-weight: 200; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraLight.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 300; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Light.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Light.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 400; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Regular.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 500; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-Medium.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 600; "
                     'font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-SemiBold.woff') format('woff'); } "
                     "@font-face { font-family: 'Assistant'; font-style: normal; font-weight: 700; "
                     "font-display: swap; src: url('/assets/webfonts/fonts/Assistant-Bold.woff2') "
                     "format('woff2'), url('/assets/webfonts/fonts/Assistant-Bold.woff') "
                     "format('woff'); } @font-face { font-family: 'Assistant'; font-style: normal; "
                     'font-weight: 800; font-display: swap; src: '
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff2') format('woff2'), "
                     "url('/assets/webfonts/fonts/Assistant-ExtraBold.woff') format('woff'); } "
                     'body, html { font-family: "Assistant", -apple-system, BlinkMacSystemFont, '
                     '"Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica '
                     'Neue", sans-serif; } .gssb_c{ width:220px !important; right: 20px '
                     '!important; left: auto !important; } .report-body h2, .report-body h3 { '
                     'line-height: normal !important; } .css-vubbuv { -webkit-user-select: none; '
                     '-moz-user-select: none; -ms-user-select: none; user-select: none; width:',
         'source_id': 73393,
         'title': None,
         'url': 'https://www.gminsights.com/industry-analysis/freight-brokerage-market'},
 73397: {'raw_text': 'body{display:none !important;} if (self === top) { var antiClickjack = '
                     'document.getElementById("antiClickjack"); '
                     'antiClickjack.parentNode.removeChild(antiClickjack); } else { top.location = '
                     'self.location; } Wms Recykling Sp. z o.o. Company Profile - Poland | '
                     'Financials &amp; Key Executives | EMIS /* styles from '
                     'style-header-in-view-20200306.min.css, was in style-store-new.scss, which is '
                     'moved before closing body tag */ header{display:block}header #main-menu ul '
                     'li .main-sub-menu .ul:after,header #main-menu ul li .main-sub-menu '
                     '.ul:before,header #main-menu ul li>a:after,header #main-menu ul '
                     'li>a:before,header #top-menu ul:after,header #top-menu ul:before,header '
                     '#top-menu:after,header #top-menu:before{content:" ";display:table}header '
                     '#main-menu ul li .main-sub-menu .ul:after,header #main-menu ul '
                     'li>a:after,header #top-menu ul:after,header '
                     '#top-menu:after{clear:both}[class*=span-]{display:inline-block;vertical-align:middle}#top-menu-2 '
                     'a:hover .span-emis-bag,.span-emis-bag{vertical-align:top;margin:0 .6875rem 0 '
                     "0;width:1.125rem;height:1.375rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag.svg'),none;background-repeat:no-repeat}a:hover "
                     ".span-emis-bag{background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.svg'),none;background-repeat:no-repeat}.span-emis-bag-2{vertical-align:bottom;margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.75rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.svg'),none;background-repeat:no-repeat}.span-store-basket-70,.span-store-basket-ff{margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.25rem;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.png');background-image:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.svg'),none;background-repeat:no-repeat}.span-store-basket-70{margin:0 "
                     '.6875rem 0 '
                     "0;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-70.png');background-image:url('//static-emis.emis.com/emiscom/img/span-sto",
         'source_id': 73397,
         'title': None,
         'url': 'https://www.emis.com/php/company-profile/PL/Wms_Recykling_Sp_z_oo_en_14347646.html'},
 73398: {'raw_text': 'body{display:none !important;} if (self === top) { var antiClickjack = '
                     'document.getElementById("antiClickjack"); '
                     'antiClickjack.parentNode.removeChild(antiClickjack); } else { top.location = '
                     'self.location; } Wms Sp. z o.o. (Tarnow) Company Profile - Poland | '
                     'Financials &amp; Key Executives | EMIS /* styles from '
                     'style-header-in-view-20200306.min.css, was in style-store-new.scss, which is '
                     'moved before closing body tag */ header{display:block}header #main-menu ul '
                     'li .main-sub-menu .ul:after,header #main-menu ul li .main-sub-menu '
                     '.ul:before,header #main-menu ul li>a:after,header #main-menu ul '
                     'li>a:before,header #top-menu ul:after,header #top-menu ul:before,header '
                     '#top-menu:after,header #top-menu:before{content:" ";display:table}header '
                     '#main-menu ul li .main-sub-menu .ul:after,header #main-menu ul '
                     'li>a:after,header #top-menu ul:after,header '
                     '#top-menu:after{clear:both}[class*=span-]{display:inline-block;vertical-align:middle}#top-menu-2 '
                     'a:hover .span-emis-bag,.span-emis-bag{vertical-align:top;margin:0 .6875rem 0 '
                     "0;width:1.125rem;height:1.375rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag.svg'),none;background-repeat:no-repeat}a:hover "
                     ".span-emis-bag{background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.svg'),none;background-repeat:no-repeat}.span-emis-bag-2{vertical-align:bottom;margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.75rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.svg'),none;background-repeat:no-repeat}.span-store-basket-70,.span-store-basket-ff{margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.25rem;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.png');background-image:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.svg'),none;background-repeat:no-repeat}.span-store-basket-70{margin:0 "
                     '.6875rem 0 '
                     "0;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-70.png');background-image:url('//static-emis.emis.com/emiscom/img/span-stor",
         'source_id': 73398,
         'title': None,
         'url': 'https://www.emis.com/php/company-profile/PL/Wms_Sp_z_oo__Tarnow__en_13403541.html'},
 73401: {'raw_text': 'Just a moment... '
                     '*{box-sizing:border-box;margin:0;padding:0}html{line-height:1.15;-webkit-text-size-adjust:100%;color:#313131;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe '
                     'UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif,"Apple Color '
                     'Emoji","Segoe UI Emoji","Segoe UI Symbol","Noto Color '
                     'Emoji"}body{display:flex;flex-direction:column;height:100vh;min-height:100vh}.main-content{margin:8rem '
                     'auto;padding-left:1.5rem;max-width:60rem}@media (width Enable JavaScript and '
                     'cookies to continue ',
         'source_id': 73401,
         'title': None,
         'url': 'https://www.fortunebusinessinsights.com/freight-brokerage-market-115322'},
 73416: {'raw_text': 'body{display:none !important;} if (self === top) { var antiClickjack = '
                     'document.getElementById("antiClickjack"); '
                     'antiClickjack.parentNode.removeChild(antiClickjack); } else { top.location = '
                     'self.location; } Scheldebouw B.V. Sp. z o.o. Oddzial W Polsce Company '
                     'Profile - Poland | Financials &amp; Key Executives | EMIS /* styles from '
                     'style-header-in-view-20200306.min.css, was in style-store-new.scss, which is '
                     'moved before closing body tag */ header{display:block}header #main-menu ul '
                     'li .main-sub-menu .ul:after,header #main-menu ul li .main-sub-menu '
                     '.ul:before,header #main-menu ul li>a:after,header #main-menu ul '
                     'li>a:before,header #top-menu ul:after,header #top-menu ul:before,header '
                     '#top-menu:after,header #top-menu:before{content:" ";display:table}header '
                     '#main-menu ul li .main-sub-menu .ul:after,header #main-menu ul '
                     'li>a:after,header #top-menu ul:after,header '
                     '#top-menu:after{clear:both}[class*=span-]{display:inline-block;vertical-align:middle}#top-menu-2 '
                     'a:hover .span-emis-bag,.span-emis-bag{vertical-align:top;margin:0 .6875rem 0 '
                     "0;width:1.125rem;height:1.375rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag.svg'),none;background-repeat:no-repeat}a:hover "
                     ".span-emis-bag{background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-h.svg'),none;background-repeat:no-repeat}.span-emis-bag-2{vertical-align:bottom;margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.75rem;background:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.png');background-image:url('//static-emis.emis.com/emiscom/img/span-emis-bag-2.svg'),none;background-repeat:no-repeat}.span-store-basket-70,.span-store-basket-ff{margin:0 "
                     '.3125rem 0 '
                     "0;width:1.4375rem;height:1.25rem;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.png');background-image:url('//static-emis.emis.com/emiscom/img/span-store-basket-ff.svg'),none;background-repeat:no-repeat}.span-store-basket-70{margin:0 "
                     '.6875rem 0 '
                     "0;background:url('//static-emis.emis.com/emiscom/img/span-store-basket-70.png');background-image:url('//static-emis.emis.com/",
         'source_id': 73416,
         'title': None,
         'url': 'https://www.emis.com/php/company-profile/PL/Scheldebouw_BV_Sp_z_oo_Oddzial_W_Polsce_en_3740181.html'},
 73430: {'raw_text': 'Number of Pages: 256\n'
                     '\n'
                     '2024 ANNUAL REPORT \n'
                     '\n'
                     '# READY FOR MORE Contents The Company \n'
                     '\n'
                     '3 Key Figures 4 Editorial 6 Boards and committees \n'
                     '\n'
                     '6 Members of and mandates held by the Board of Management 7 Members of and '
                     'mandates held by the Supervisory Board \n'
                     '\n'
                     '10 Report of the Supervisory Board \n'
                     '\n'
                     'Combined Management Report \n'
                     '\n'
                     '15 Preliminary remarks 16 General information \n'
                     '\n'
                     '16 Business model 18 Express division 20 Global Forwarding, Freight division '
                     '22 Supply Chain division 24 eCommerce division 25 Post & Parcel Germany '
                     'division 27 Strategy 29 Research and development 29 Steering metrics \n'
                     '\n'
                     '33 Report on economic position \n'
                     '\n'
                     '33 Overall assessment of the Board of Management 35 Economic parameters 36 '
                     'Significant events 36 Results of operations 38 Express division 40 Global '
                     'Forwarding, Freight division 41 Supply Chain division 43 eCommerce division '
                     '43 Post & Parcel Germany division 45 Financial position 50 Net assets \n'
                     '\n'
                     '52 Deutsche Post AG (HGB) \n'
                     '\n'
                     '52 Deutsche Post AG as parent company 52 Employees 52 Results of operations '
                     '53 Net assets and financial position 55 Expected developments, opportunities '
                     'and risks \n'
                     '\n'
                     '56 Group Sustainability Statement/ Nonfinancial Statement \n'
                     '\n'
                     '56 Spotlight on sustainability 57 General information (ESRS 2 BP-1 and BP-2) '
                     '59 Sustainability in business conduct (ESRS 2 GOV-1 to GOV-5) 64 Strategy, '
                     'business model, value chain, interests and views of stakeholders, and '
                     'material impacts, risks and opportunities (ESRS 2 SBM-1 to SBM-3) 71 '
                     'Environment (ESRS E1) 93 Own workforce (ESRS S1) 107 Workers in the value '
                     'chain (ESRS S2) 109 Business conduct (ESRS G1) 115 Entity specific: '
                     'Cybersecurity \n'
                     '\n'
                     '123 Expected developments, opportunities and risks \n'
                     '\n'
                     '123 Forecast period 123 Future economic prospects 124 Expected developments '
                     '125 Opportunity and risk management 129 Opportunity and risk categories 137 '
                     'Internal control system 139 Overall assessment of the Board of Management \n'
                     '\n'
                     '140 Governance \n'
                     '\n'
                     '140 Annual Corporate Governance Statement 149 Disclosures required by '
                     'takeover law \n'
                     '\n'
                     'Consolidated Financial Statements \n'
                     '\n'
                     '151 Income statement 152 Statement of comprehensive income 153 Balance sheet '
                     '154 Cash flow statement 155 Statement of changes in equity 156 Notes to the '
                     'Consolidate',
         'source_id': 73430,
         'title': None,
         'url': 'https://group.dhl.com/content/dam/deutschepostdhl/en/media-center/investors/documents/annual-reports/DHL-Group-2024-Annual-Report.pdf'}}
