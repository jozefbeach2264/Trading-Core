def parse_command(input_str: str):
    parts = input_str.strip().split()
    command = parts[0]
    args = parts[1:]
    return command, args