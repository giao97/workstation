const axios = require('axios');
const cheerio = require('cheerio');
const RSSParser = require('rss-parser');

const rssParser = new RSSParser();

/**
 * 新闻与政策抓取器
 * 支持: 东方财富、新浪财经、CNBC、Reuters RSS、证监会、央行、交易所公告
 */
class NewsPolicyFetcher {
  constructor() {
    this.axios = axios.create({
      timeout: 20000,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      }
    });
  }

  // ========== 新闻抓取 ==========

  async fetchEastMoneyNews(limit = 30) {
    try {
      // 东方财富要闻 API
      const url = `https://www.eastmoney.com/api/news?type=cywjh&pageSize=${limit}`;
      const resp = await this.axios.get(url);
      const items = resp.data?.result?.data || [];
      return items.map(item => ({
        title: item.title,
        summary: item.summary || item.content?.slice(0, 200),
        url: item.url,
        source: '东方财富',
        category: '财经要闻',
        publishTime: item.showTime || item.pubDate,
        fetchedAt: new Date().toISOString()
      }));
    } catch (err) {
      console.error('[News] EastMoney failed:', err.message);
      return [];
    }
  }

  async fetchSinaNews(limit = 20) {
    try {
      const url = 'https://feed.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=50&page=1&r=0.5';
      const resp = await this.axios.get(url);
      const items = resp.data?.result?.data || [];
      return items.slice(0, limit).map(item => ({
        title: item.title,
        summary: item.summary || '',
        url: item.url,
        source: '新浪财经',
        category: '股市新闻',
        publishTime: item.ctime ? new Date(item.ctime * 1000).toISOString() : null,
        fetchedAt: new Date().toISOString()
      }));
    } catch (err) {
      console.error('[News] Sina failed:', err.message);
      return [];
    }
  }

  async fetchCNBCNews(limit = 20) {
    try {
      const feed = await rssParser.parseURL('https://www.cnbc.com/id/100003114/device/rss/rss.html');
      return feed.items.slice(0, limit).map(item => ({
        title: item.title,
        summary: item.contentSnippet || item.content?.slice(0, 300),
        url: item.link,
        source: 'CNBC',
        category: 'Global Markets',
        publishTime: item.isoDate,
        fetchedAt: new Date().toISOString()
      }));
    } catch (err) {
      console.error('[News] CNBC RSS failed:', err.message);
      return [];
    }
  }

  async fetchReutersNews(limit = 20) {
    try {
      const feed = await rssParser.parseURL('https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=reuters-best');
      return feed.items.slice(0, limit).map(item => ({
        title: item.title,
        summary: item.contentSnippet || '',
        url: item.link,
        source: 'Reuters',
        category: 'Business',
        publishTime: item.isoDate,
        fetchedAt: new Date().toISOString()
      }));
    } catch (err) {
      console.error('[News] Reuters RSS failed:', err.message);
      return [];
    }
  }

  // ========== 政策抓取 ==========

  async fetchCSRCPolicy(limit = 15) {
    try {
      // 证监会最新政策 (通过爬虫)
      const url = 'http://www.csrc.gov.cn/csrc/c100028/common_list.shtml';
      const resp = await this.axios.get(url);
      const $ = cheerio.load(resp.data);
      const items = [];
      $('.er_list li, .fl_list li, .er_right_list li').each((i, el) => {
        if (i >= limit) return false;
        const $el = $(el);
        const title = $el.find('a').text().trim();
        const href = $el.find('a').attr('href');
        const date = $el.find('span').text().trim();
        if (title) {
          items.push({
            title,
            summary: '',
            url: href?.startsWith('http') ? href : `http://www.csrc.gov.cn${href}`,
            source: '中国证监会',
            category: '监管政策',
            publishTime: date,
            fetchedAt: new Date().toISOString()
          });
        }
      });
      return items;
    } catch (err) {
      console.error('[Policy] CSRC failed:', err.message);
      return [];
    }
  }

  async fetchPBCPolicy(limit = 10) {
    try {
      const url = 'http://www.pbc.gov.cn/zhengcehuobisi/11140/index.html';
      const resp = await this.axios.get(url);
      const $ = cheerio.load(resp.data);
      const items = [];
      $('.newslist li, .newsList li, .list li').each((i, el) => {
        if (i >= limit) return false;
        const $el = $(el);
        const title = $el.find('a').text().trim();
        const href = $el.find('a').attr('href');
        const date = $el.find('span, .date').text().trim();
        if (title) {
          items.push({
            title,
            summary: '',
            url: href?.startsWith('http') ? href : `http://www.pbc.gov.cn${href}`,
            source: '中国人民银行',
            category: '货币政策',
            publishTime: date,
            fetchedAt: new Date().toISOString()
          });
        }
      });
      return items;
    } catch (err) {
      console.error('[Policy] PBC failed:', err.message);
      return [];
    }
  }

  async fetchExchangeNotices() {
    try {
      // 上交所公告 RSS
      const sseFeed = await rssParser.parseURL('http://www.sse.com.cn/lawsregulations/lawsAndRegulations/news/').catch(() => null);
      // 深交所公告
      const szseItems = await this.fetchSZSENotices();

      const items = [];
      if (sseFeed?.items) {
        items.push(...sseFeed.items.slice(0, 10).map(item => ({
          title: item.title,
          summary: item.contentSnippet || '',
          url: item.link,
          source: '上海证券交易所',
          category: '交易所公告',
          publishTime: item.isoDate,
          fetchedAt: new Date().toISOString()
        })));
      }
      items.push(...szseItems);
      return items;
    } catch (err) {
      console.error('[Policy] Exchange notices failed:', err.message);
      return [];
    }
  }

  async fetchSZSENotices(limit = 10) {
    try {
      const url = 'https://www.szse.cn/api/search/content';
      const resp = await this.axios.post(url, {
        keyword: '',
        time: 7,
        range: 'title',
        channelCode: []
      }, { headers: { 'Content-Type': 'application/json' } }).catch(() => ({ data: { data: [] } }));
      const items = (resp.data?.data || []).slice(0, limit);
      return items.map(item => ({
        title: item.title,
        summary: item.content?.slice(0, 200) || '',
        url: item.url,
        source: '深圳证券交易所',
        category: '交易所公告',
        publishTime: item.publishTime,
        fetchedAt: new Date().toISOString()
      }));
    } catch (err) {
      return [];
    }
  }

  // ========== 批量抓取 ==========

  async fetchAllNews() {
    const [eastmoney, sina, cnbc, reuters] = await Promise.all([
      this.fetchEastMoneyNews(),
      this.fetchSinaNews(),
      this.fetchCNBCNews(),
      this.fetchReutersNews()
    ]);
    const all = [...eastmoney, ...sina, ...cnbc, ...reuters];
    // 去重并排序
    const seen = new Set();
    return all.filter(item => {
      if (seen.has(item.title)) return false;
      seen.add(item.title);
      return true;
    }).sort((a, b) => new Date(b.publishTime || 0) - new Date(a.publishTime || 0));
  }

  async fetchAllPolicy() {
    const [csrc, pbc, exchange] = await Promise.all([
      this.fetchCSRCPolicy(),
      this.fetchPBCPolicy(),
      this.fetchExchangeNotices()
    ]);
    return [...csrc, ...pbc, ...exchange].sort((a, b) => new Date(b.publishTime || 0) - new Date(a.publishTime || 0));
  }
}

module.exports = NewsPolicyFetcher;
