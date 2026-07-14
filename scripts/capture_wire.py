from x4cir.cli import main

raise SystemExit(main(["record-wire", *(__import__("sys").argv[1:])]))
