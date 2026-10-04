"""黄金调查来源候选集。

描述“某类问题优先查哪些网站”。
sources 的排列顺序就是默认优先级；tier 越小，证据越接近原始来源。
"""

SOURCE_TIERS = {
    1: "交易所、监管机构、央行或产品发行人",
    2: "专业黄金机构或官方统计机构",
    3: "大型财经新闻机构",
    4: "聚合资讯，仅用于发现线索",
}


SOURCE_UNIVERSES = {
    "china_spot": {
        "name": "中国现货与基准金",
        "keywords": ["上海金", "SHAU", "Au99.99", "Au(T+D)", "人民币黄金"],
        "sources": [
            {"domain": "sge.com.cn", "name": "上海黄金交易所", "tier": 1, "purpose": "基准价、现货合约与历史行情"},
            {"domain": "pbc.gov.cn", "name": "中国人民银行", "tier": 1, "purpose": "黄金储备与货币政策"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "中国及全球黄金供需"},
            {"domain": "cnstock.com", "name": "上海证券报", "tier": 3, "purpose": "国内市场解释与采访"},
            {"domain": "cs.com.cn", "name": "中国证券报", "tier": 3, "purpose": "国内市场解释与采访"},
            {"domain": "stcn.com", "name": "证券时报", "tier": 3, "purpose": "国内市场解释与采访"},
        ],
    },
    "london_spot": {
        "name": "伦敦现货与国际基准金",
        "keywords": ["伦敦金", "国际现货黄金", "LBMA", "XAU/USD", "黄金现货"],
        "sources": [
            {"domain": "lbma.org.uk", "name": "LBMA", "tier": 1, "purpose": "LBMA Gold Price 与市场标准"},
            {"domain": "ice.com", "name": "ICE Benchmark Administration", "tier": 1, "purpose": "黄金基准价管理信息"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "全球黄金价格、供需与研究"},
            {"domain": "reuters.com", "name": "Reuters", "tier": 3, "purpose": "国际市场事件与交叉验证"},
            {"domain": "bloomberg.com", "name": "Bloomberg", "tier": 3, "purpose": "国际市场事件与交叉验证"},
            {"domain": "ft.com", "name": "Financial Times", "tier": 3, "purpose": "国际市场背景分析"},
        ],
    },
    "comex_futures": {
        "name": "COMEX 黄金期货",
        "keywords": ["COMEX", "纽约金", "黄金期货", "GC期货", "美黄金"],
        "sources": [
            {"domain": "cmegroup.com", "name": "CME Group", "tier": 1, "purpose": "合约、行情、成交与持仓"},
            {"domain": "cftc.gov", "name": "CFTC", "tier": 1, "purpose": "COT 持仓分类与历史数据"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "全球期货市场汇总"},
            {"domain": "reuters.com", "name": "Reuters", "tier": 3, "purpose": "期货波动原因与事件核验"},
            {"domain": "bloomberg.com", "name": "Bloomberg", "tier": 3, "purpose": "期货波动原因与事件核验"},
            {"domain": "cnbc.com", "name": "CNBC", "tier": 3, "purpose": "美国市场新闻补充"},
        ],
    },
    "gold_etf": {
        "name": "黄金 ETF",
        "keywords": ["黄金ETF", "GLD", "IAU", "ETF流入", "ETF持仓"],
        "sources": [
            {"domain": "spdrgoldshares.com", "name": "SPDR Gold Shares", "tier": 1, "purpose": "GLD 持仓、净值与金条清单"},
            {"domain": "ishares.com", "name": "iShares", "tier": 1, "purpose": "IAU 持仓、净值与基金文件"},
            {"domain": "sec.gov", "name": "SEC", "tier": 1, "purpose": "基金法定披露文件"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "全球 ETF 持仓和资金流汇总"},
            {"domain": "reuters.com", "name": "Reuters", "tier": 3, "purpose": "ETF 资金流背景解释"},
            {"domain": "bloomberg.com", "name": "Bloomberg", "tier": 3, "purpose": "ETF 资金流背景解释"},
        ],
    },
    "macro_drivers": {
        "name": "黄金宏观驱动",
        "keywords": ["美联储", "实际利率", "美元", "通胀", "央行购金", "地缘政治"],
        "sources": [
            {"domain": "federalreserve.gov", "name": "Federal Reserve", "tier": 1, "purpose": "FOMC 决议、讲话与货币政策"},
            {"domain": "fred.stlouisfed.org", "name": "FRED", "tier": 2, "purpose": "利率、美元及宏观时间序列"},
            {"domain": "bls.gov", "name": "BLS", "tier": 1, "purpose": "美国通胀与就业数据"},
            {"domain": "bea.gov", "name": "BEA", "tier": 1, "purpose": "美国 GDP 与 PCE 数据"},
            {"domain": "home.treasury.gov", "name": "U.S. Treasury", "tier": 1, "purpose": "国债收益率与财政信息"},
            {"domain": "pbc.gov.cn", "name": "中国人民银行", "tier": 1, "purpose": "中国货币政策与黄金储备"},
            {"domain": "ecb.europa.eu", "name": "ECB", "tier": 1, "purpose": "欧元区货币政策"},
            {"domain": "imf.org", "name": "IMF", "tier": 2, "purpose": "各国官方黄金储备和宏观数据"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "央行购金与黄金需求"},
            {"domain": "reuters.com", "name": "Reuters", "tier": 3, "purpose": "事件发生时间与市场反应"},
        ],
    },
    "physical_retail": {
        "name": "实物金与银行黄金产品",
        "keywords": ["金条", "金币", "首饰金", "积存金", "银行金价", "零售金价"],
        "sources": [
            {"domain": "sge.com.cn", "name": "上海黄金交易所", "tier": 1, "purpose": "国内批发市场参考价格"},
            {"domain": "icbc.com.cn", "name": "工商银行", "tier": 1, "purpose": "本行黄金产品与规则"},
            {"domain": "boc.cn", "name": "中国银行", "tier": 1, "purpose": "本行黄金产品与规则"},
            {"domain": "ccb.com", "name": "建设银行", "tier": 1, "purpose": "本行黄金产品与规则"},
            {"domain": "gold.org", "name": "世界黄金协会", "tier": 2, "purpose": "金条、金币和首饰需求"},
            {"domain": "cnstock.com", "name": "上海证券报", "tier": 3, "purpose": "零售市场调查"},
        ],
    },
    "discovery_news": {
        "name": "新闻线索补充",
        "keywords": [],
        "sources": [
            {"domain": "reuters.com", "name": "Reuters", "tier": 3, "purpose": "国际新闻线索"},
            {"domain": "bloomberg.com", "name": "Bloomberg", "tier": 3, "purpose": "国际财经线索"},
            {"domain": "xinhuanet.com", "name": "新华社", "tier": 3, "purpose": "国内政策与事件线索"},
            {"domain": "cnstock.com", "name": "上海证券报", "tier": 3, "purpose": "国内财经线索"},
            {"domain": "cs.com.cn", "name": "中国证券报", "tier": 3, "purpose": "国内财经线索"},
            {"domain": "stcn.com", "name": "证券时报", "tier": 3, "purpose": "国内财经线索"},
            {"domain": "eastmoney.com", "name": "东方财富", "tier": 4, "purpose": "发现候选文章，不直接作为首选证据"},
            {"domain": "sina.com.cn", "name": "新浪财经", "tier": 4, "purpose": "发现候选文章，不直接作为首选证据"},
            {"domain": "10jqka.com.cn", "name": "同花顺", "tier": 4, "purpose": "发现候选文章，不直接作为首选证据"},
        ],
    },
}

