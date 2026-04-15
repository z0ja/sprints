import random

n=10000//3

with open("fichier.txt","w") as f:
    for i in range(n):
        for j in range(n):
            f.write(str(random.randint(n//4,n)))