# coding=utf-8
from __future__ import print_function
from __future__ import division

import argparse
import logging
from collections import Counter, defaultdict
import os
import sys
import time
from dp.title_normalizer import TitleNormalizer
import utils.constants as K
from utils.text_utils import tokenizer, _getLnrm
from utils.misc_utils import load_id2title, load_redirects
# from hanziconv import HanziConv

logging.basicConfig(format='%(asctime)s: %(filename)s:%(lineno)d: %(message)s', level=logging.INFO)


def read_surface_title_maps(s2t, t2s, cand_file, normalizer, add_ascii=False, tokenize=False, lang="en"):
    bad = 0
    start = time.time()
    for idx, line in enumerate(cand_file):
        line = line.strip()
        parts = line.split("\t")
        if len(parts) < 2:
            # logging.info("bad line %d %s", idx, line)
            bad += 1
            continue
        # Surface links should be lowercase before query, to reduce sparse counts
        s = parts[0].lower()

        # Candidate titles should always be "canonical"
        t = normalizer.normalize(title=parts[1])
        if t == K.NULL_TITLE:
            continue
        # s = s.lower()
        if not tokenize:
            if s not in s2t: s2t[s] = []
            s2t[s].append(t)
            if t not in t2s: t2s[t] = []
            t2s[t].append(s)
            if add_ascii:
                ascii_s = get_ascii_phrase(s)
                if ascii_s not in s2t: s2t[ascii_s] = []
                s2t[ascii_s].append(t)
                if t not in t2s: t2s[t] = []
                t2s[t].append(ascii_s)
            if lang == "zh":
                # TODO this conversion improves recall, but hurts acc@1 slightly
                sm_s = HanziConv.toSimplified(s)
                if sm_s not in s2t: s2t[sm_s] = []
                s2t[sm_s].append(t)
                if t not in t2s: t2s[t] = []
                t2s[t].append(sm_s)
        else:
            surf_tokens = tokenizer(s, lang)  # BOTTLENECK!
            for surf_token in surf_tokens:
                if surf_token not in s2t: s2t[surf_token] = []
                s2t[surf_token].append(t)
                if t not in t2s: t2s[t] = []
                t2s[t].append(surf_token)
            if add_ascii:
                for surf_token in surf_tokens:
                    ascii_s = get_ascii_phrase(surf_token)
                    if ascii_s not in s2t: s2t[ascii_s] = []
                    s2t[ascii_s].append(t)
                    if t not in t2s: t2s[t] = []
                    t2s[t].append(ascii_s)

            if lang == "zh":
                for surf_token in surf_tokens:
                    sm_surf_token = HanziConv.toSimplified(surf_token)
                    if sm_surf_token not in s2t: s2t[sm_surf_token] = []
                    s2t[sm_surf_token].append(t)
                    if t not in t2s: t2s[t] = []
                    t2s[t].append(sm_surf_token)

        if idx > 0 and idx % 1000000 == 0:
            logging.info("read %d lines bad frac:%f", idx, (1.0 * bad / idx))
    end = time.time()
    logging.info("loaded surface links file in %d secs", (end - start))
    # return s2t, t2s


def compute_x_given_y(path, y2x):
    start = time.time()
    with open(path, "w") as y2x2prob:
        for y in y2x:
            x2cnt = Counter(y2x[y])
            total = sum(x2cnt.values())
            for x in x2cnt:
                prob = x2cnt[x] / total
                buf = "%s\t%s\t%f\t%d/%d\n" % (y, x, prob, x2cnt[x], total)
                y2x2prob.write(buf)
    end = time.time()
    logging.info("computed in %d secs", (end - start))


def compute_phrase_prob(p2t, t2p, out_prefix):
    path = out_prefix + "." + "p2t2prob"
    if os.path.exists(path):
        logging.info("%s already exists.", path)
    else:
        logging.info("Calculating p(title | phrase)...")
        compute_x_given_y(path=path, y2x=p2t)

    path = out_prefix + "." + "t2p2prob"
    if os.path.exists(path):
        logging.info("%s already exists.", path)
    else:
        logging.info("Calculating p(phrase | title)...")
        compute_x_given_y(path=path, y2x=t2p)


def compute_word_prob(w2t, t2w, out_prefix):
    path = out_prefix + "." + "w2t2prob"
    if os.path.exists(path):
        logging.info("%s already exists.", path)
    else:
        logging.info("Calculating p(title | word)...")
        compute_x_given_y(path, y2x=w2t)

    path = out_prefix + "." + "t2w2prob"
    if os.path.exists(path):
        logging.info("%s already exists.", path)
    else:
        logging.info("Calculating p(word | title)...")
        compute_x_given_y(path, y2x=t2w)


def get_tokens(lang, raw_title, add_ascii):
    ans = []
    if lang == "zh":
        sm_title = HanziConv.toSimplified(raw_title)
        if "·" in raw_title:
            title_tokens = raw_title.split("·")
            sm_title_tokens = sm_title.split("·")
        elif "_" in raw_title:
            title_tokens = raw_title.split("_")
            sm_title_tokens = sm_title.split("_")
        else:
            title_tokens = raw_title.split(" ")
            sm_title_tokens = sm_title.split(" ")
        ans += title_tokens + sm_title_tokens
    else:
        title_tokens = raw_title.lower().strip().split("_")
        ans += title_tokens
        if add_ascii:
            ascii_tokens = [get_ascii_phrase(x) for x in title_tokens]
            ans += ascii_tokens
    return ans


def add_titles_and_redirects_tokens(t2w, w2t, t2id, is_redirect, redirects, lang, add_ascii=False):
    # need tokenizer
    for raw_title in t2id:  # title should match itself as a surface
        if raw_title in is_redirect and raw_title in redirects:
            nrm = redirects[raw_title]
        else:
            nrm = raw_title

        all_tokens = get_tokens(lang, raw_title, add_ascii)

        for tok in all_tokens:
            if tok not in w2t:
                w2t[tok] = []
            w2t[tok].append(nrm)
            if nrm not in t2w:
                t2w[nrm] = []
            t2w[nrm].append(tok)


def get_ascii_phrase(phrase):
    tokens = phrase.split(" ")
    ascii_phrase = " ".join([_getLnrm(token) for token in tokens])
    return ascii_phrase


def get_phrases(lang, raw_title, add_ascii):
    ans = []

    if lang == "zh":
        ans.append(raw_title)
        if "·" in raw_title:
            title_phrase = raw_title.replace("·", " ").lower().strip()
        elif "_" in raw_title:
            title_phrase = raw_title.replace("_", " ").lower().strip()
        else:
            title_phrase = raw_title
        ans.append(title_phrase)

        if " " in title_phrase:
            # Add chinese version with phrase tokens concat
            concat = title_phrase.replace(" ", "")
            ans.append(concat)
    else:
        title_phrase = raw_title.replace("_", " ").lower().strip()
        ans.append(title_phrase)

    if lang == "zh":
        # Add simplified chinese version
        sm_title_phrase = HanziConv.toSimplified(title_phrase)  # TTT TT --> SSS SS
        ans.append(sm_title_phrase)

    if add_ascii:
        ascii_phrase = get_ascii_phrase(title_phrase)
        ans.append(ascii_phrase)

    return ans


def add_titles_and_redirects(p2t, t2p, t2id, is_redirect, redirects, lang, add_ascii=False):
    # title should match itself as a surface
    for idx, raw_title in enumerate(t2id):
        if raw_title in is_redirect and raw_title in redirects:
            nrm = redirects[raw_title]
        else:
            nrm = raw_title

        title_phrases = get_phrases(lang, raw_title, add_ascii)

        for ph in title_phrases:
            if ph not in p2t: p2t[ph] = []
            p2t[ph].append(nrm)

            if nrm not in t2p: t2p[nrm] = []
            t2p[nrm].append(ph)

    logging.info("added titles as default surfaces")

    # for redirect in redirects:
    #     if lang == "zh":
    #         redirect_phrase = redirect.replace("·", " ").lower().strip()
    #     else:
    #         redirect_phrase = redirect.replace("_", " ").lower().strip()
    #     title = redirects[redirect]
    #
    #     if redirect_phrase not in p2t:
    #         p2t[redirect_phrase] = []
    #     p2t[redirect_phrase].append(title)
    #
    #     if title not in t2p:
    #         t2p[title] = []
    #     t2p[title].append(redirect_phrase)
    #
    #     if lang == "zh":
    #         sm_redirect_phrase = HanziConv.toSimplified(redirect_phrase)
    #         if sm_redirect_phrase not in p2t:
    #             p2t[sm_redirect_phrase] = []
    #         p2t[sm_redirect_phrase].append(title)
    #         t2p[title].append(sm_redirect_phrase)
    # logging.info("added redirects as default surfaces")


def add_unicode(st2t, phrase=False):
    for s in st2t:
        if phrase:
            tokens = s.split(" ")
            ascii_phrase = " ".join([_getLnrm(token) for token in tokens])
            st2t[ascii_phrase] = st2t[s]
        else:
            token = s
            ascii_token = _getLnrm(token)
            st2t[ascii_token] = st2t[s]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Compute P(t|s) and P(s|t).')
    parser.add_argument('--links', type=str, required=True, help='file contains surface --> link in all of wikipedia '
                                                                 '(eg. enwiki/surface_links)')
    parser.add_argument('--id2t', type=str, required=True, help='id --> title')
    parser.add_argument('--redirects', type=str, required=True, help='redirect --> title')
    parser.add_argument('--out_prefix', type=str, required=True,
                        help='path to write the prob files. eg. enwiki/enwiki-20170520')
    parser.add_argument('--lang', type=str, required=True, help='language code')
    parser.add_argument('--mode', type=str, required=True, help='phrase,word')
    parser.add_argument('--debug', action="store_true", help='interactive')
    parser.add_argument('--add_ascii', action="store_true",
                        help='whether to add ascii version. DO NOT do it for Arabic etc.')
    args = parser.parse_args()
    args = vars(args)

    start = time.time()
    links = args["links"]
    out_prefix = args["out_prefix"]
    lang = args["lang"]
    if lang == "tr" and not args["add_ascii"]:
        logging.info("Turning ascii on because its Turkish...")
        # sys.exit(0)
        args["add_ascii"] = True
    redirect2title = load_redirects(args["redirects"])
    id2t, t2id, is_redirect_map = load_id2title(args["id2t"])
    normalizer = TitleNormalizer(lang=lang,
                                 redirect_map=redirect2title,
                                 t2id=t2id)
    # print(len(is_redirect_map))
    # print(len(redirect2title))
    # assert len(is_redirect_map) == len(redirect2title)
    if args["mode"] == "phrase":
        # NEEDS ~ 20G of RAM
        ph2t = defaultdict(lambda: list)  # phrase to titles
        t2ph = defaultdict(lambda: list)  # titles to phrase

        add_titles_and_redirects(p2t=ph2t, t2p=t2ph, t2id=t2id, redirects=redirect2title, lang=lang,
                                 add_ascii=args["add_ascii"], is_redirect=is_redirect_map)
        compute_phrase_prob(p2t=ph2t, t2p=t2ph, out_prefix=out_prefix + ".tnr")

        read_surface_title_maps(s2t=ph2t, t2s=t2ph, cand_file=open(links), normalizer=normalizer, lang=lang,
                                add_ascii=args["add_ascii"])
        compute_phrase_prob(p2t=ph2t, t2p=t2ph, out_prefix=out_prefix)

    if args["mode"] == "word":
        # NEEDS ~ 25G of RAM
        wo2t = defaultdict(lambda: list)  # word to titles
        t2wo = defaultdict(lambda: list)  # titles to word

        add_titles_and_redirects_tokens(w2t=wo2t, t2w=t2wo, t2id=t2id, redirects=redirect2title, lang=lang,
                                        add_ascii=args["add_ascii"], is_redirect=is_redirect_map)
        # if args["add_ascii"]:
        #     add_unicode(st2t=wo2t, phrase=False)
        compute_word_prob(w2t=wo2t, t2w=t2wo, out_prefix=out_prefix + ".tnr")

        read_surface_title_maps(s2t=wo2t, t2s=t2wo, cand_file=open(links), normalizer=normalizer, tokenize=True,
                                lang=lang, add_ascii=args["add_ascii"])
        compute_word_prob(w2t=wo2t, t2w=t2wo, out_prefix=out_prefix)
        end = time.time()
        logging.info("took %s hours", (end - start) / 3600)
