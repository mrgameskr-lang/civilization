"""Test the reusable journal with a deterministic letter-counting game."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.game_journal import append_turn, new_journal, restore_journal, save_journal
from civsim.storage import canonical_line


def create(seed):
    return {"score":seed, "turn":0}


def step(game, command):
    game["turn"] += 1
    letters = [] if command is None else command["letters"]
    game["score"] += len(letters)
    return {"글자":letters, **game}


class JournalTests(unittest.TestCase):
    def test_empty_and_wait_turn_and_unicode_replay_match_existing_canonical_bytes(self):
        empty = new_journal(-3)
        self.assertEqual(restore_journal(empty,create,step),create(-3))
        game,journal = create(-3),empty
        for command in ({"letters":["별","海","a"]}, None):
            annual = step(game,command)
            journal = append_turn(journal, command_dict_or_none=command, annual_record=annual)
            self.assertEqual(journal["turns"][-1], {
                "year":game["turn"], "command":command,
                "record_sha256":sha256(canonical_line(annual)).hexdigest(),
            })
        self.assertEqual(len(empty["turns"]),0)
        saved = json.loads(json.dumps(journal))
        self.assertEqual(restore_journal(saved,create,step),game)

    def test_append_returns_independent_json_and_step_cannot_change_recorded_commands(self):
        original={"letters":["x","y"]}
        first=append_turn(new_journal(0),original,2)
        second=append_turn(first,None,2)
        original["letters"].clear()
        second["turns"][0]["command"]["letters"].append("z")
        self.assertEqual(first["turns"][0]["command"],{"letters":["x","y"]})
        def pop_step(state,command):
            amount=len(command["letters"])
            command["letters"].clear()
            state["score"] += amount
            return amount
        self.assertEqual(restore_journal(first,create,pop_step)["score"],2)
        self.assertEqual(first["turns"][0]["command"],{"letters":["x","y"]})

    def test_replay_stops_at_first_inconsistent_turn(self):
        game = create(9)
        j = new_journal(9)
        for command in (None,{"letters":["a"]},None):
            j=append_turn(j,command,step(game,command))
        for alteration in ("command","hash","seed"):
            with self.subTest(alteration=alteration):
                bad=deepcopy(j)
                if alteration=="command": bad["turns"][1]["command"]={"letters":[]}
                elif alteration=="hash": bad["turns"][1]["record_sha256"]="0"*64
                else: bad["seed"]+=1
                called=[]
                def spy(state,command):
                    called.append(command)
                    return step(state,command)
                n=1 if alteration=="seed" else 2
                with self.assertRaisesRegex(ValueError,fr"turn {n}"):
                    restore_journal(bad,create,spy)
                self.assertEqual(len(called),n)

    def test_reject_malformed_journals_before_calling_user_code(self):
        valid=append_turn(new_journal(1),None,None)
        for corruption in ("schema","year","boolean_year","bad_hash","command","extra","turns"):
            with self.subTest(corruption=corruption):
                bad=deepcopy(valid)
                if corruption=="schema": bad["schema"]="future"
                elif corruption=="year": bad["turns"][0]["year"]=2
                elif corruption=="boolean_year": bad["turns"][0]["year"]=True
                elif corruption=="bad_hash": bad["turns"][0]["record_sha256"]="F"*64
                elif corruption=="command": bad["turns"][0]["command"]=[1]
                elif corruption=="extra": bad["turns"][0]["payload"]=True
                else: bad["turns"]="1"
                with self.assertRaises(ValueError):
                    restore_journal(bad,lambda _: self.fail("invalid input reached game factory"),step)

    def test_non_json_values_and_ambiguous_command_keys_rejected(self):
        for bad in (True,"1"):
            with self.assertRaises(ValueError): new_journal(bad)
        loop=[]
        loop.append(loop)
        for invalid in ({1:"not a string key"}, {"a":float('nan')}, {"a":{1}}, {"a":(3,)}, {"a":loop}):
            with self.subTest(kind=type(invalid)),self.assertRaises(ValueError):
                append_turn(new_journal(0),invalid,None)
        for record in (float("inf"), {1:"x"}, loop):
            with self.assertRaises(ValueError): append_turn(new_journal(0),None,record)

    def test_save_is_canonical_and_does_not_overwrite_prior_file(self):
        j=append_turn(new_journal(1),None,step(create(1),None))
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"saves"/"turn.json"
            save_journal(path,j)
            raw=path.read_bytes()
            self.assertEqual(raw,canonical_line(j))
            self.assertEqual(restore_journal(json.loads(raw),create,step),{"score":1,"turn":1})
            with self.assertRaises(FileExistsError): save_journal(path,new_journal(2))
            self.assertEqual(path.read_bytes(),raw)
            other=path.with_name("invalid.json")
            with self.assertRaises(ValueError): save_journal(other,{"schema":"future"})
            self.assertFalse(other.exists())

    def test_concurrent_writers_publish_exactly_one_complete_journal(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"saved.json"
            start=Barrier(2)
            def attempt(seed):
                journal=new_journal(seed)
                start.wait()
                try:
                    save_journal(path,journal)
                except FileExistsError:
                    return None
                return seed
            with ThreadPoolExecutor(max_workers=2) as workers:
                winners=[seed for seed in workers.map(attempt,(17,24)) if seed is not None]
            self.assertEqual(len(winners),1)
            self.assertEqual(path.read_bytes(),canonical_line(new_journal(winners[0])))
            self.assertEqual(list(path.parent.iterdir()),[path])
