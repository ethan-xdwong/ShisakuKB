# 衡石手册问答

以静态 HTML 手册为唯一正文。服务启动时抽取小节、做结构检查，并用中文分词和 BM25 检索。答案由本机 Ollama 的 `openbmb/MiniCPM5-2B` 生成，来源附带可打开的段落链接。

衡石手册说明业务单据、审核，以及与 WMS、自有物流 TMS 或第三方承运商、财务系统的对接。流程图使用 Mermaid，同一路径同时写成步骤，索引不收录图的源码。

## 准备

需要 Python 3.11+，以及已启动的 Ollama，模型名为 `openbmb/MiniCPM5-2B`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.indexer
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。左侧是手册，右侧是问答。勾选「只看检索」时只返回 BM25 结果，不调用模型。手册也可以单独打开 `http://127.0.0.1:8000/kb/`。

可选环境变量：

- `OLLAMA_HOST`：默认 `http://127.0.0.1:11434`
- `OLLAMA_MODEL`：默认 `openbmb/MiniCPM5-2B`

服务每次启动都会根据 `kb/` 下的 HTML 重建 `data/index.json`。缺锚点、缺首段、标题重复、流程图没有配套步骤，或术语表中的规范词没有出现在其他正文里，启动会失败并打印原因。

## 提问示例

- 阶梯价
- 存货
- 物流异常如何处理
