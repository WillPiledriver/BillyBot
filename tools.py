import re
import json
import random as rand
import requests
import json


def roll(s, mod=0):
    if re.match(re.compile("^[0-9]+d[0-9]+$"), s.lower()):
        p = s.lower().split("d")
        rolls = [rand.randint(1, int(p[1])) for i in range(int(p[0]))]
    elif re.match(re.compile("^[0-9]+$"), s):
        rolls = [int(s)]
    else:
        print("You fucked up")
        rolls = [0]
    return rolls, sum(rolls) + mod


def ask_randomorg(num, dt):
    result = requests.get(f"https://www.random.org/integers/?num={num}&min=1&max={dt}&col=1&base=10&format=plain&rnd=new").content.split()
    return [int(x) for x in result]


def randomorg_roll(s, mod=0):
    if re.match(re.compile("^[0-9]+d[0-9]+$"), s.lower()):
        p = s.lower().split("d")
        rolls = ask_randomorg(p[0], p[1])

    elif re.match(re.compile("^[0-9]+$"), s):
        rolls = [int(s)]
    else:
        print("You fucked up")
        rolls = [0]
    return rolls, sum(rolls) + mod


def quantum_roll(n, dietype):
    response = requests.post("https://qrng.anu.edu.au/wp-admin/admin-ajax.php",
                             data={"repeats": "yesrepeat", "set_num": "1", "rep_num": str(n), "min_num": "1",
                                   "max_num": str(dietype), "action": "dice_action", "dice_nonce_field": "7b8ea17b2f",
                                   "_wp_http_referer": "/dice-throw/"})
    jr = json.loads(response.text.replace("\\", "")[1:len(response.text.replace("\\", "")) - 1])
    if jr["type"] == "success":
        r = jr["output"][0]
    else:
        print("failed")
        return None

    print(r)
    return r


def rw_dict(filename, mode, data=None, create=False):
    if mode == "r":
        try:
            with open(filename, mode) as file:
                result = json.load(file)
        except FileNotFoundError:
            if create:
                with open(filename, "w+") as file:
                    file.write("{}")
                    print(f'Json file "{filename}" created')
            else:
                print(f'File {filename} not found, and not created.')
            result = {}
    else:
        with open(filename, mode) as file:
            json.dump(data, file)
        result = None

    return result
