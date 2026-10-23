def next_pin_serial(current_serial):
    prefix = ''.join(filter(str.isalpha, current_serial))
    number = int(''.join(filter(str.isdigit, current_serial)))

    if number < 999:
        return f"{prefix} {number + 1:03d}"
    else:
        new_prefix = increment_pin_letters(prefix)
        return f"{new_prefix}001"

def increment_pin_letters(s):
    if not s:
        return 'A'
    s = list(s.upper())
    i = len(s) - 1
    while i >= 0:
        if s[i] != 'Z':
            s[i] = chr(ord(s[i]) + 1)
            return ''.join(s)
        s[i] = 'A'
        i -= 1
    return 'A' + ''.join(s)


def next_box_serial(current_serial):
    prefix = ''.join(filter(str.isalpha, current_serial))
    number = int(''.join(filter(str.isdigit, current_serial)))

    if number < 999:
        return f"{prefix} {number + 1:03d}"
    else:
        new_prefix = increment_box_letters(prefix)
        return f"{new_prefix}001"

def increment_box_letters(s):
    if not s:
        return 'A'
    s = list(s.upper())
    i = len(s) - 1
    while i >= 0:
        if s[i] != 'Z':
            s[i] = chr(ord(s[i]) + 1)
            return ''.join(s)
        s[i] = 'A'
        i -= 1
    return 'A' + ''.join(s)
