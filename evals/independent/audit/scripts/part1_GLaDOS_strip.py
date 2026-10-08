import re,sys
t=open(sys.argv[1]).read()
out=[l for l in t.split("\n") if not re.match(r"^R\d+,",l) and not l.startswith("route,stop")]
s="\n".join(out); s=re.sub(r"\n{3,}","\n\n",s)
open(sys.argv[2],"w").write(s); print(len(s))
