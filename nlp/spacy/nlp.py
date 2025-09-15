import spacy

nlp = spacy.load("en_core_web_lg")

txt = "The Top 100 Companies of the World: U.S. vs Everyone. When it comes to breaking down the top 100 companies of the world, the United States still commands the largest slice of the pie. Throughout the 20th century and before globalization reached its current peaks, American companies made the country an economic powerhouse and the source of a majority of global market value. But even as countries like China have made headway with multi-billion dollar companies of their own, and the market’s most important sectors have shifted, the U.S. has managed to stay on top."

doc = nlp(txt)

for ent in doc.ents:
    print(ent.text, ent.label_)