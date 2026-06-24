import sys, types, json

def tool(name):
    def deco(f):
        f.func = f
        return f
    return deco

src = open("src/tools.py").read()
start = src.index('@tool("lookup_technique")')
rest = src[start + 1:]
end = rest.find('\n@tool(')
body = src[start:] if end == -1 else src[start:start + 1 + end]

# run the extracted function in a namespace that already has `tool` and `json`
ns = {"tool": tool, "json": json, "re": __import__("re")}
exec(body, ns)
lookup_technique = ns["lookup_technique"]

for q in ["model poisoning", "gps spoofing", "SDN routing manipulation",
          "OTA firmware update", "schema type confusion", "AML.T9999"]:
    print("=" * 60)
    print("QUERY:", q)
    print(lookup_technique.func(q))