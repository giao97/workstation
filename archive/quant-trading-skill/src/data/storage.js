const fs = require('fs-extra');
const path = require('path');

class Storage {
  constructor(dataDir) {
    this.dataDir = dataDir;
    fs.ensureDirSync(dataDir);
  }

  getDateStr(date = new Date()) {
    return date.toISOString().split('T')[0].replace(/-/g, '');
  }

  async saveMarketData(symbol, data) {
    const dateStr = this.getDateStr();
    const dir = path.join(this.dataDir, 'market', dateStr);
    await fs.ensureDir(dir);
    const filePath = path.join(dir, `${symbol.replace(/[\/.]/g, '_')}.json`);
    await fs.writeJson(filePath, data, { spaces: 2 });
    return filePath;
  }

  async saveNews(data) {
    const dateStr = this.getDateStr();
    const dir = path.join(this.dataDir, 'news', dateStr);
    await fs.ensureDir(dir);
    const filePath = path.join(dir, 'news.json');
    await fs.writeJson(filePath, data, { spaces: 2 });
    return filePath;
  }

  async savePolicy(data) {
    const dateStr = this.getDateStr();
    const dir = path.join(this.dataDir, 'policy', dateStr);
    await fs.ensureDir(dir);
    const filePath = path.join(dir, 'policy.json');
    await fs.writeJson(filePath, data, { spaces: 2 });
    return filePath;
  }

  async loadMarketData(symbol, dateStr) {
    const filePath = path.join(this.dataDir, 'market', dateStr, `${symbol.replace(/[\/.]/g, '_')}.json`);
    if (await fs.pathExists(filePath)) {
      return fs.readJson(filePath);
    }
    return null;
  }

  async loadLatestMarketData(symbol) {
    const marketDir = path.join(this.dataDir, 'market');
    if (!await fs.pathExists(marketDir)) return null;
    const dirs = (await fs.readdir(marketDir)).sort().reverse();
    for (const dir of dirs) {
      const data = await this.loadMarketData(symbol, dir);
      if (data) return data;
    }
    return null;
  }
}

module.exports = Storage;
