"""Register page parsers (Türkiye BKÜ, Egypt APC) on minimal pages shaped like the real ones (S6, 2026-09-16)."""
from residuecheck.registers import parse_apc, parse_bku, split_substances

BKU = """<html><body><h2>Ruhsat Detay</h2><h3>AZOSTAR 320 SC (İMAL)</h3><table>
<tr><td>Formulasyonu</td><td>SC (Süspansiyon Konsantre)</td></tr>
<tr><td>Aktif Madde</td><td>120 g/l Azoxystrobin + 200 g/l Tebuconazole</td></tr>
<tr><td>Ruhsat Numarası</td><td>1234</td></tr>
<tr><td>Geçerlilik Süresi</td><td>01.02.2031</td></tr></table></body></html>"""

APC = """<html><body><table>
<tr><td>الإسم التجاري</td><td><span id="content_ContentPlaceHolder1_dvProduct_lblName">ليكوبار 40% SE</span></td></tr>
<tr><td>المواد الفعالة</td><td><a id="content_ContentPlaceHolder1_dvProduct_DataList1_HyperLink1_0">Azoxystrobin</a> +
<a id="content_ContentPlaceHolder1_dvProduct_DataList1_HyperLink1_1">Propiconazole</a></td></tr>
<tr><td>الموقف من التسجيل</td><td><a id="content_ContentPlaceHolder1_dvProduct_hlStatus">مسجل</a></td></tr>
<tr><td>فترة ما قبل الحصاد</td><td><span id="content_ContentPlaceHolder1_gvCropRates_repCropRatesDetails_0_lblPHI_0">14 يوم</span></td></tr>
</table></body></html>"""


def test_parse_bku():
    p = parse_bku(BKU)
    assert p["trade_name"] == "AZOSTAR 320 SC"
    assert p["substances"] == ["Azoxystrobin", "Tebuconazole"]
    assert p["valid_until"] == "2031-02-01" and p["licence_no"] == "1234"


def test_parse_apc():
    p = parse_apc(APC)
    assert (p["trade_name"], p["substances"], p["status"]) == ("ليكوبار 40% SE", ["Azoxystrobin", "Propiconazole"], "مسجل")
    assert p["pre_harvest_intervals"] == ["14 يوم"]


def test_empty_pages_return_none():
    assert parse_bku("<html><h3>The resource you are looking for might have been removed</h3></html>") is None
    assert parse_apc('<html><span id="content_ContentPlaceHolder1_dvProduct_lblName"></span></html>') is None


def test_split_substances():
    assert split_substances("%25,2 Boscalid + %12,8 Pyraclostrobin") == ["Boscalid", "Pyraclostrobin"]
    assert split_substances("1x10^9 cfu/g Bacillus subtilis") == ["Bacillus subtilis"]
    assert split_substances("% 60 Tribenuron-methyl + % 20 Florasulam") == ["Tribenuron-methyl", "Florasulam"]
