# Run against the REAL corpus to calibrate the relevance floor.
# Prints IDF of the tokens in your failing queries so we set the floor from data.
import json, re, math
idx = json.load(open("corpus-index/technique_index.json"))
STOP = {'the','a','an','of','in','on','at','to','for','and','or','with','from',
        'by','as','via','into','attack','technique','system','data','access',
        'adversary','target','network','layer','model','ai','ml','using','use','used'}
def toks(t): return [w for w in re.findall(r'[a-z0-9]{3,}', t.lower()) if w not in STOP]
N = len(idx); df = {}
for v in idx.values():
    for t in set(toks(v.get("name","")+" "+v.get("description",""))):
        df[t] = df.get(t,0)+1
def idf(t): return round(math.log((N+1)/(df.get(t,0)+1))+1.0, 2)

print(f"corpus size N = {N}")
for term in ["poisoning","spoofing","gps","firmware","schema","routing","sdn",
             "rag","ephemeris","manipulation","confusion","ota"]:
    print(f"  {term:14s} df={df.get(term,0):4d}  idf={idf(term):5.2f}  name-weight(x2)={idf(term)*2:.2f}")
print()
print("Floor guidance: set SINGLE_TOKEN_WEIGHT_FLOOR just BELOW the name-weight")
print("of your rarest meaningful single-token query (e.g. 'gps','rag','sdn'),")
print("and ABOVE the name-weight of generic terms ('spoofing','manipulation').")