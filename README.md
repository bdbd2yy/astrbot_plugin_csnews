# CS更新推送

浏览和推送cs2更新的一个AstrBot插件

## 命令

- `csnews ls`: 列出一年内的cs新闻
- `csnews ls <page>`: 列出新闻列表中某一页的选项
- `csnews <index>`: 从列表中选中某条新闻并展示具体内容
- `csupdates ls`: 列出最近10次cs更新列表
- `csupdates <index>`: 从列表中选中某次更新并展示具体内容
- `csnews on`: 在群聊中开启更新自动推送
- `csnews off`: 在群聊中关闭更新自动推送

## 输出样例

```text
26.04.29 | 新闻

= Title

Content

refs: Counter-Strike official link
```

## 数据源

插件从[cs官方网站](https://www.counter-strike.net/)上获取新闻以及更新
