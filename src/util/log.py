debug_mode = True

class Logger:

    @staticmethod
    def log(msg):
        if debug_mode:
            print(f"\n[DEBUG]\n{msg}")