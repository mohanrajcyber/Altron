from pathlib import Path

root = Path(__file__).resolve().parents[1]
api_path = root.parent / "API.txt"
example = (root / ".env.example").read_text(encoding="utf-8")
keys = [
    line.strip()
    for line in api_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if line.strip().startswith("nvapi-")
]
names = ["NVIDIA_NIM_API_KEY", "NVIDIA_NIM_API_KEY_2", "NVIDIA_NIM_API_KEY_3"]
used = 0
out: list[str] = []
for line in example.splitlines():
    placed = False
    for i, name in enumerate(names):
        if line.startswith(name + "=") and i < len(keys):
            out.append(f"{name}={keys[i]}")
            used += 1
            placed = True
            break
    if not placed:
        out.append(line)
(root / ".env").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {used} nvidia keys to .env")
