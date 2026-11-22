"""MCP 프로토콜(stdio) 연결 테스트. 사용: uv run python mcp_protocol_test.py"""
import asyncio, json, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent

async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("search_bids", {"category": "물품", "keyword": "노트북", "max_results": 2})
            data = json.loads(res.content[0].text)
            print("search_bids 물품 노트북:", data["total_count"], "건,", [i["bidNtceNm"] for i in data["items"]])

asyncio.run(main())
