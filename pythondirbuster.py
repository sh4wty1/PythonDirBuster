import requests;
def Apresentation():    
    print("")
    print("  _____       _   _                   _____  _      _               _   ")
    print(" |  __ \     | | | |                 |  __ \(_)    | |             | |  ")
    print(" | |__) |   _| |_| |__   ___  _ __   | |  | |_ _ __| |__  _   _ ___| |_ ")
    print(" |  ___/ | | | __| '_ \ / _ \| '_ \  | |  | | | '__| '_ \| | | / __| __|")
    print(" | |   | |_| | |_| | | | (_) | | | | | |__| | | |  | |_) | |_| \__ \ |_ ")
    print(" |_|    \__, |\__|_| |_|\___/|_| |_| |_____/|_|_|  |_.__/ \__,_|___/\__|")
    print("         __/ |                                                          ")
    print("        |___/                                                           ")
    print("")
    print("Coded by @nglshawty1 :)")
    print("")
    print("Warning: You NEED to put the 'https://' part of the URL, otherwise, it will not work. Example:")
    print("Incorrect: google.com")
    print("Correct: https://google.com/")
    print("This can take really a long time due to the huge wordlist, so be patient lol...")
    print("")

def Main():
    Apresentation();
    file = open("Subdomain.txt")
    lines = file.readlines()
    target = input('Type your URL -> ')
    for word in lines:
        word = word.replace('\n', '');
        r = requests.get(target+word)
        if 200 <= r.status_code <= 299:
            print("########################")
            print(word,"// status code:", r.status_code)
            print("########################")
        else:
            print("Offline")
Main()
# Arrumar uma falha