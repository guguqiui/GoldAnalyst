import unittest
from unittest.mock import patch

from gold_analyst.server import new_run
from gold_analyst.tools.base import ToolContext
from gold_analyst.tools.sge import SGEDataTool


DAILY_HTML = """<html><title>每日行情</title><table>
<tr><th>日期</th><th>合约</th><th>开盘价</th><th>最高价</th><th>最低价</th><th>收盘价</th>
<th>涨跌</th><th>涨跌幅</th><th>加权平均价</th><th>成交量</th><th>成交金额</th><th>持仓</th><th>交收方向</th><th>交收量</th></tr>
<tr><td>2026-09-30</td><td>Au99.99</td><td>850</td><td>860</td><td>848</td><td>858</td><td>8</td><td>0.94%</td><td>856</td><td>100</td><td>85600</td><td>200</td><td></td><td>0</td></tr>
<tr><td>2026-10-02</td><td>Au99.99</td><td>860</td><td>870</td><td>859</td><td>868</td><td>10</td><td>1.17%</td><td>866</td><td>120</td><td>103920</td><td>220</td><td></td><td>0</td></tr>
</table></html>""".encode()

BENCHMARK_HTML = """<html><title>上海金基准价行情</title><table>
<tr><th>序号</th><th>交易日期</th><th>合约</th><th>场次</th><th>轮次</th><th>价格</th><th>买量</th><th>卖量</th><th>补充量</th></tr>
<tr><td>1</td><td>2026/10/02</td><td>SHAU</td><td>早盘</td><td>1</td><td>866.20</td><td>10</td><td>8</td><td>2</td></tr>
</table></html>""".encode()


class SGEDataToolTests(unittest.TestCase):
    def tool(self):
        run = new_run("multi", "黄金价格", "source_first")
        return SGEDataTool(ToolContext(run, lambda *args: None)), run

    @patch("gold_analyst.tools.sge.fetch")
    def test_non_trading_day_returns_latest_effective_date(self, fake_fetch):
        fake_fetch.return_value = (
            DAILY_HTML, "text/html; charset=utf-8", "https://www.sge.com.cn/sjzx/quotation_daily_new",
        )
        tool, run = self.tool()

        result = tool.execute("2026-10-04", "daily", "Au99.99")

        self.assertEqual(result["requested_date"], "2026-10-04")
        self.assertEqual(result["effective_date"], "2026-10-02")
        self.assertTrue(result["fallback_applied"])
        self.assertFalse(result["no_data"])
        self.assertTrue(result["comparison_ready"])
        self.assertEqual(result["contract"], "Au99.99")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(len(result["previous_rows"]), 1)
        self.assertEqual(result["rows"][0]["contract"], "Au99.99")
        self.assertEqual(result["rows"][0]["close"], "868")
        self.assertEqual(result["previous_effective_date"], "2026-09-30")
        self.assertEqual(result["previous_rows"][0]["close"], "858")
        self.assertEqual(len(run["evidence"]), 1)
        self.assertNotIn("导航", run["evidence"][0]["text"])
        requested_url = fake_fetch.call_args.args[0]
        self.assertIn("start_date=2026-09-20", requested_url)
        self.assertIn("end_date=2026-10-04", requested_url)

    @patch("gold_analyst.tools.sge.fetch")
    def test_benchmark_rows_preserve_session_and_round(self, fake_fetch):
        fake_fetch.return_value = (
            BENCHMARK_HTML, "text/html", "https://www.sge.com.cn/sjzx/shanghaiAuAuto",
        )
        tool, _ = self.tool()

        result = tool.execute("2026-10-04", "benchmark", "SHAU")

        self.assertEqual(result["effective_date"], "2026-10-02")
        self.assertEqual(result["rows"][0]["session"], "早盘")
        self.assertEqual(result["rows"][0]["round"], "1")
        self.assertEqual(result["rows"][0]["price"], "866.20")

    @patch("gold_analyst.tools.sge.fetch")
    def test_empty_table_is_explicitly_no_data(self, fake_fetch):
        html = b"<html><title>Daily</title><table><tr><th>Date</th><th>Contract</th></tr></table></html>"
        fake_fetch.return_value = (html, "text/html", "https://www.sge.com.cn/sjzx/quotation_daily_new")
        tool, run = self.tool()

        result = tool.execute("2026-10-04", "daily", "Au99.99")

        self.assertTrue(result["no_data"])
        self.assertEqual(result["effective_date"], "")
        self.assertEqual(result["previous_effective_date"], "")
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["previous_rows"], [])
        self.assertFalse(result["comparison_ready"])
        self.assertIn("没有返回可解析的数据行", run["evidence"][0]["text"])

    @patch("gold_analyst.tools.sge.fetch")
    def test_never_borrows_previous_price_from_another_contract(self, fake_fetch):
        html = """<html><table>
        <tr><td>2026-10-02</td><td>Au99.95</td><td>900</td><td>905</td><td>899</td><td>904.50</td><td>1</td><td>0.1%</td><td>903</td><td>2</td><td>1800</td><td>-</td><td></td><td></td></tr>
        <tr><td>2026-10-01</td><td>Au99.95</td><td>-</td><td>-</td><td>-</td><td>-</td><td></td><td></td><td>-</td><td>0</td><td>0</td><td>-</td><td></td><td></td></tr>
        <tr><td>2026-10-01</td><td>Au99.99</td><td>890</td><td>900</td><td>889</td><td>897.53</td><td>1</td><td>0.1%</td><td>895</td><td>10</td><td>8950</td><td>-</td><td></td><td></td></tr>
        </table></html>""".encode()
        fake_fetch.return_value = (html, "text/html", "https://www.sge.com.cn/sjzx/quotation_daily_new")
        tool, _ = self.tool()

        result = tool.execute("2026-10-04", "daily", "Au99.95")

        self.assertEqual(result["effective_date"], "2026-10-02")
        self.assertEqual(result["previous_effective_date"], "")
        self.assertEqual(result["previous_rows"], [])
        self.assertFalse(result["comparison_ready"])


if __name__ == "__main__":
    unittest.main()
