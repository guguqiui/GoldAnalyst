"""入口：python main.py 打开本地界面；python main.py --demo 直接生成示例报告。"""
import argparse
from gold_analyst.server import serve, execute, new_run
from gold_analyst.storage import markdown


def main():
    parser = argparse.ArgumentParser(description="黄金信息调查员")
    parser.add_argument("--demo", action="store_true", help="不联网、不用 Key，运行虚构教学样例")
    parser.add_argument("--investigate", metavar="URL_OR_CLAIM", help="使用 OpenAI 调查真实新闻链接或说法")
    parser.add_argument("--multi", action="store_true", help="用三个研究员并行调查，再由裁判合并")
    parser.add_argument("--strategy", default="source_first", choices=["source_first", "scope_first", "counter_first"])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.demo and (args.investigate or args.multi):
        parser.error("--demo 不能与 --investigate/--multi 同时使用")
    if args.multi and not args.investigate:
        parser.error("--multi 需要同时提供 --investigate")
    if args.demo or args.investigate:
        mode = "demo" if args.demo else "multi" if args.multi else "live"
        run = execute(new_run(mode, args.investigate or "", args.strategy))
        if run["status"] == "failed":
            print(run["error"])
            raise SystemExit(1)
        print(markdown(run))
        print(f"\n完整过程保存在 reports/{run['id']}.json")
    else:
        serve(args.port)


if __name__ == "__main__":
    main()
