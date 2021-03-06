"""PhpSploit shell interface.

Unheriting the shnake's Shell class, the PhpSploit shell interface
provides interactive use of commands.

"""
# pylint: disable=too-many-lines
# pylint: disable=too-many-public-methods

import os
import traceback
import subprocess

import shnake

import core
from core import session, tunnel, plugins, encoding
import datatypes
from datatypes import Path
import ui.output
from ui.color import colorize
import ui.input
import utils.path

READLINE_COMPLETER_DELIMS = ' \t\n`~!@#$%^&*()=+[{]}\\|;:\'",<>/?'


class Shell(shnake.Shell):
    """PhpSploit shell interface"""

    prompt = colorize('%Lined', 'phpsploit', '%Reset', ' > ')

    _nocmd = "[-] Unknown Command: %s"
    nohelp = "[-] No help for: %s"
    error = "[!] %s"

    bind_command = None

    def __init__(self):
        self.last_exception = None
        super().__init__()
        try:
            import readline
            readline.set_history_length(session.Hist.MAX_SIZE)
            readline.set_completer_delims(READLINE_COMPLETER_DELIMS)
        except ImportError:
            pass

    def init(self):
        """phpsploit interface init"""
        # load phpsploit plugins list
        plugins.blacklist = self.get_names(self, "do_")
        plugins.reload(verbose=False)

    # pylint: disable=arguments-differ
    def precmd(self, argv):
        """Handle pre command hooks such as session aliases"""
        # Make 'nocmd' error message verbose if tunnel is connected
        self.nocmd = self._nocmd
        if tunnel:
            msg = "use `run` plugin to run remote command"
            self.nocmd += colorize("%Dim", " (%s)" % msg)
        # Reset backlog before each command except backlog
        if self.bind_command:
            if len(argv) == 1 and argv[0] == "exit":
                # self.bind_command = None
                pass
            else:
                argv.insert(0, self.bind_command)
        if argv and argv[0] != "backlog":
            self.stdout.backlog = ""
        # Alias Handler
        try:
            cmds = self.parseline(session.Alias[argv[0]])
        except (KeyError, IndexError):
            return argv
        self.interpret(cmds[:-1], precmd=(lambda x: x))
        return cmds[-1] + argv[1:]

    def onecmd(self, argv):
        if "id" in session.Compat and session.Compat["id"] == "v1":
            print("[-] Warning: You are using a v1-compatible session file")
            print("[-]          please upgrade $TARGET with new $BACKDOOR")
            print("[-]          and run `session upgrade` when done.")
            print("")
        print("[#] %s: Running..." % debug_cmdrepr(argv))
        return super().onecmd(argv)

    def postcmd(self, retval, argv):
        """Post command hook

        - Redraw shell prompt

        """
        int_retval = self.return_errcode(retval)
        print("[#] %s: Returned %d" % (debug_cmdrepr(argv), int_retval))
        # redraw shell prompt after each command
        prompt_elems = ["%Lined", "phpsploit"]
        if tunnel:
            # if remote shell, add target hostname to prompt
            prompt_elems += ["%Reset", "(", "%BoldRed",
                             tunnel.hostname, "%Reset", ")"]
        if self.bind_command:
            # If a command is binded to the prompt
            prompt_elems += ["%ResetBoldWhite", " #", self.bind_command]
        prompt_elems += ["%Reset", " > "]
        self.prompt = colorize(*prompt_elems)

        return retval

    def completenames(self, text, *ignored):
        """Add aliases and plugins for completion"""
        result = super().completenames(text, ignored)
        result += session.Alias.keys()
        if tunnel:
            result += plugins.keys()
        return ([x for x in list(set(result)) if x.startswith(text)])

    def onexception(self, exception):
        """Add traceback handler to onexception"""
        self.last_exception = exception
        return super().onexception(exception)

    def default(self, argv):
        """Fallback to plugin command (if any)"""
        if tunnel and argv[0] in plugins.keys():
            return plugins.run(argv)
        return super().default(argv)

    #################
    # COMMAND: exit #
    @staticmethod
    def complete_exit(text, *_):
        """autocompletion for `exit` command"""
        keys = ["--force"]
        return [x for x in keys if x.startswith(text)]

    def do_exit(self, argv):
        """Quit current shell interface

        SYNOPSIS:
            exit [--force]

        OPTIONS:
            --force
                When called to leave the framework, this
                option forces exit, avoiding warning message
                if current session has not been saved to a file,
                or has changed since last save.

        DESCRIPTION:
            If current phpsploit session is connected to $TARGET,
            this command disconnects the user from remote session.
            Otherwise, if the interface is not connected, this
            command leaves the phpsploit framework.
        """
        if len(argv) == 2 and argv[1] == "--force":
            force_exit = True
        elif len(argv) == 1:
            force_exit = False
        else:
            self.interpret("help exit")
            return False

        if self.bind_command:
            self.bind_command = None
        elif tunnel:
            tunnel.close()
        else:
            if not force_exit:
                try:
                    session_changed = session.diff(None)
                except OSError:
                    session_changed = bool(tunnel.has_been_active())
                if session_changed:
                    msg = "Do you really want to exit without saving session ?"
                    if ui.input.Expect(False)(msg):
                        return False
            exit()
        return True # make pylint happy

    ####################
    # COMMAND: corectl #
    @staticmethod
    def complete_corectl(text, *_):
        """autocompletion for `corectl` command"""
        keys = ["stack-traceback", "reload-plugins",
                "python-console", "display-http-requests"]
        return [x for x in keys if x.startswith(text)]

    def do_corectl(self, argv):
        """Advanced core debugging utils

        SYNOPSIS:
            corectl <TOOL>

        CORECTL TOOLS:
        --------------

        stack-traceback
            Print the full track trace of last python exception.

            Error messages (lines that starts with a `[!]` red tag)
            are generated by a thrown exception.
            The `stack-traceback` tool displays the full python
            stack trace of the last thrown exception.
            This command is useful for debugging purposes.

            NOTE: stack traceback is NOT saved in session files

        reload-plugins
            Reload all phpsploit plugins.

            By default, the list of phpsploit plugins is loaded
            once only, when the framework starts.
            Therefore, plugin developpers may want to reload
            the plugins in order to be able to test their
            plugin modifications without having to restart the
            framework each time.

        python-console
            Run a python interpreter.

            The python console interpreter is a good gateway for deep
            debugging, or to get help about a phpsploit module, class,
            object, such as the plugin developpers API.

            For help with the API, run the following commands inside
            the python console:
            >>> import api
            >>> help(api)

        display-http-requests
            Display HTTP(s) request(s) for debugging

            Shows all HTTP(s) request(s) that where sent in the last
            remote command execution.

            NOTE: http requests are NOT saved in session files
            WARNING: don't works with HTTPS requests (see issue #29 on github)
        """
        argv.append('')

        if argv[1] == "stack-traceback":
            if self.last_exception:
                exc = self.last_exception
                exc = traceback.format_exception(type(exc),
                                                 exc,
                                                 exc.__traceback__)
                # a small patch for traceback from plugins, remove trash lines
                for idx, line in enumerate(exc):
                    if ('File "<frozen importlib._bootstrap>"' in line
                            and '_call_with_frames_removed' in line):
                        exc = exc[(idx + 1):]
                        header = "Traceback (most recent call last):"
                        exc.insert(0, header + os.linesep)
                        break
                print(colorize("%Red", "".join(exc)))
            else:
                print("[-] Exception stack is empty")

        elif argv[1] == "reload-plugins":
            plugins.reload(verbose=True)

        elif argv[1] == "python-console":
            from ui import console
            console = console.Console()
            console.banner = "Phpsploit corectl: python console interpreter"
            console()

        elif argv[1] == "display-http-requests":
            requests = enumerate(tunnel.get_raw_requests(), 1)
            if not requests:
                print("[-] No HTTP(s) requests were sent up to now")
                return
            for num, request in requests:
                print("#" * 78)
                print("### REQUEST %d" % num)
                print("#" * 78)
                print(encoding.decode(request))
        else:
            self.interpret("help corectl")

    ####################
    # COMMAND: history #
    def do_history(self, argv):
        """Command line history

        SYNOPSIS:
            history
            history <[COUNT]>

        DESCRIPTION:
            Returns a formatted string giving the event number and
            contents for each of the events in the history list
            except for current event.

            If [COUNT] is specified, only the [COUNT] most recent
            events are displayed.

            > history 10
              - Display last 10 commands of the history.
            > history
              - Display the full history of events.
        """
        import readline

        argv.append('9999999999')

        try:
            count = int(argv[1])
        except ValueError:
            return self.interpret("help history")

        last = readline.get_current_history_length()
        while last > session.Hist.MAX_SIZE:
            readline.remove_history_item(0)
            last -= 1
        first = last - count
        if first < 1:
            first = 1
        for i in range(first, last):
            cmd = readline.get_history_item(i)
            print("{:4d}  {:s}".format(i, cmd))

    ####################
    # COMMAND: exploit #
    @staticmethod
    def complete_exploit(text, *_):
        """autocompletion for `exploit` command"""
        keys = ["--get-backdoor"]
        return [x for x in keys if x.startswith(text)]

    def do_exploit(self, argv):
        """Spawn a shell from target server

        SYNOPSIS:
            exploit [--get-backdoor]

        DESCRIPTION:
            This command send an HTTP request to the remote server
            url (defined by the $TARGET setting).
            If $TARGET is correctly backdoored with the
            phpsploit backdoor, the request remotely executes
            the session opener in order to retrieve environment
            variables, and spawn the phpsploit remote shell.

        OPTIONS:
            --get-backdoor
                Only display current backdoor, as it should be
                injected on the current or future target url.

            NOTE: The $TARGET setting should be a valid http(s) url,
            previously infected with the phpsploit backdoor.
        """
        obj = str(session.Conf.BACKDOOR(call=False))
        obj = obj.replace("%%PASSKEY%%", session.Conf.PASSKEY().upper())

        if len(argv) > 1:
            if argv[1] == "--get-backdoor":
                print(obj)
                return True
            self.interpret("help exploit")
            return False

        print("[*] Current backdoor is: " + obj + "\n")

        if tunnel:
            m = ("[*] Use `set TARGET <VALUE>` to use another url as target."
                 "\n[*] To exploit a new server, disconnect from «{}» first.")
            print(m.format(session.Env.HOST))
            return False

        if session.Conf.TARGET() is None:
            m = ("To run a remote tunnel, the backdoor shown above must be\n"
                 "manually injected in a remote server executable web page.\n"
                 "Then, use `set TARGET <BACKDOORED_URL>` and run `exploit`.")
            print(colorize("%BoldCyan", m))
            return False

        return tunnel.open()  # it raises exception if fails

    ##################
    # COMMAND: clear #
    @staticmethod
    # pylint: disable=unused-argument
    def do_clear(argv):
        """Clear the terminal screen

        SYNOPSIS:
            clear

        DESCRIPTION:
            Clear the terminal screen. This command
            is interesting for visibility purposes only.
        """
        if ui.output.isatty():
            os.system('clear')

    #################
    # COMMAND: rtfm #
    @staticmethod
    # pylint: disable=unused-argument
    def do_rtfm(argv):
        """Read the fine manual

        SYNOPSIS:
            rtfm

        DESCRIPTION:
            Display phpsploit user manual. If available, the `man`
            command is used for display. Otherwise, a text version
            of the man page is displayed in phpsploit interface.
        """
        man = Path(core.BASEDIR, 'man/phpsploit.1')
        cmd = 'man phpsploit 2>/dev/null || man %r 2>/dev/null' % man
        if os.system(cmd) != 0:
            txt_man = Path(core.BASEDIR, 'man/phpsploit.txt')
            print(txt_man.read())

    ####################
    # COMMAND: session #
    def complete_session(self, text, *_):
        """autocompletion for `session` command"""
        keys = ['save', 'diff', 'load', 'upgrade']
        # load argument is not available from remote shell:
        if self.__class__.__name__ == "MainShell":
            keys.append('load')
        return [x for x in keys if x.startswith(text)]

    @staticmethod
    def do_session(argv):
        """phpsploit session handler

        SYNOPSIS:
            session [load|diff] [<FILE>]
            session save [-f] [<FILE>]
            session upgrade

        DESCRIPTION:
            The `session` core command handles phpsploit sessions.
            Sessions can be considered as phpsploit instances. They
            handle current configuration settings, environment vars,
            command aliases, and remote tunnel attributes (if any).
            They can be saved to a file for further use.

        USAGE:
            * session [<FILE>]
                Show a nice colored representation of FILE session
                content. If called without argument, current session
                if displayed.
            * session diff [<FILE>]
                Show a textual representation of the differences
                between FILE and current session. If FILE is not set,
                the diff between session's original and current states
                if shown.
            * session save [-f] [<FILE>]
                Save current session state in FILE.
                If FILE is not set, the session is saved to it's original
                path location. It still not bound to a file, default location
                is '$SAVEPATH/phpsploit.session'.
                NOTE: The '-f' option, if used, saves the session without
                      asking user confirmation if file already exists.
            * session load [<FILE>]
                Try to load session from FILE.
                It unset, try to load session from './phpsploit.session'
            * session upgrade
                If current session file is in v1-compatible mode,
                the request handler is limited to POST method and does
                not supports multi request and stealth modules.
                This command shall be used to upgrade current session
                AFTER you upgraded the remote $TARGET with new-style
                phpsploit backdoor (which can be obtained with
                `exploit --get-backdoor` command).

        EXAMPLES:
            > session load /tmp/phpsploit.session
              - Load /tmp/phpsploit.session.
            > session save
              - Save current state to session file.

        WARNING:
            The `session load` action can't be used through a remote
            shell session. If it is the case, run `exit` to disconnect
            from remote server before launching this command.
        """
        # prevent argv IndexError
        argv += [None, None]

        # session save [<FILE>]
        if argv[1] == 'save':
            if argv[2] == '-f':
                path = argv[3]
                ask_confirmation = False
            else:
                path = argv[2]
                ask_confirmation = True
            session.dump(path, ask_confirmation=ask_confirmation)
            path = session.File if path is None else path
            session.File = path
            print("[*] Session saved into %r" % path)
        # session load [<FILE>]
        elif argv[1] == 'load':
            try:
                session.update(argv[2], update_history=True)
                print("[#] Session file correctly loaded")
            except:
                print("[#] Could not load session file")
                raise
        # session diff [<FILE>]
        elif argv[1] == 'diff':
            session.diff(argv[2], display_diff=True)
        # session upgrade
        elif argv[1] == 'upgrade':
            if "id" in session.Compat:
                print("[*] You are about to upgrade phpsploit session.")
                print("[*] Please ensure that you have correctly upgraded")
                print("[*] the remote backdoor into target URL.")
                print("[*] After session upgrade, phpsploit assumes that")
                print("[*] an up-to-date backdoor is active on $TARGET.")
                cancel = ui.input.Expect(False)
                if not cancel("Do you really want to upgrade session now ?"):
                    session.Compat = {}
                    print("[*] Session correctly upgraded")
                else:
                    print("[-] Session upgrade aborted")
            else:
                print("[-] Session already up-to-date")
        # sesion [<FILE>]
        else:
            print(session(argv[1]))

    #################
    # COMMAND: lrun #
    def do_lrun(self, argv):
        """Execute client-side shell command

        SYNOPSIS:
            lrun command [arg1 [arg2 [...] ] ]

        DESCRIPTION:
                Execute a shell command in your own operating system.
                This command works like the `exec` command in unix
                shells.

                NOTE: This core command shouldn't be confused with the
                `run` plugin, which does the same thing in the
                remotely exploited system.

        EXAMPLES:
            > lrun ls -la /
            > lrun htop
        """
        if len(argv) == 1:
            self.interpret("help lrun")
            return

        cmd = " ".join(argv[1:])

        if argv[1] != "exit":
            tmpfile = Path()
            postcmd = " ; pwd >'%s' 2>&1" % tmpfile
            subprocess.call(cmd + postcmd, shell=True)
            try:
                os.chdir(tmpfile.read())
            finally:
                del tmpfile

    ###################
    # COMMAND: source #
    def do_source(self, argv):
        """Execute a phpsploit script file

        SYNOPSIS:
            source [OPTIONS] <LOCAL_FILE>

        DESCRIPTION:
            Read [LOCAL_FILE] and executes the statements
            contained therein. As if each line was a phpsploit
            command.

        OPTIONS:
            -e
                Abort file sourcing as soon as a command
                fails (aka, returns nonzero), and return
                the code returned by the command which failed.

        EXAMPLES:
            > source /tmp/spl01t-script.phpsploit
              - Run the given script file's content, line by line
        """
        if len(argv) == 2:
            abort_on_error = False
            source_file = argv[1]
        elif len(argv) == 3 and argv[1] == "-e":
            abort_on_error = True
            source_file = argv[2]
        else:
            return self.interpret("help source")
        source_file = utils.path.truepath(source_file)
        data = open(source_file, 'r').read()
        ret = self.interpret(data, fatal_errors=abort_on_error)
        return ret

    ################
    # COMMAND: set #
    @staticmethod
    def complete_set(text, *_):
        """Use settings as `set` completers (case insensitive)"""
        result = []
        for key in session.Conf.keys():
            if key.startswith(text.upper()):
                result.append(key)
        return result

    @staticmethod
    def do_set(argv):
        """view and edit configuration settings

        SYNOPSIS:
            set [<VAR> [+] ["<VALUE>"]]

        DESCRIPTION:
            Settings are a collection of editable variables that affect
            phpsploit's core behavior.
            - Their value is bound to current session.
            - To permanently change a setting's value at start, it
            must be defined by hand on phpsploit config file.

            > set
              - Display current settings

            > set <STRING>
              - Display settings whose name starts with STRING

            > set <VAR> <VALUE>
              - Assign VALUE to VAR setting (only if it's a valid value)

            > set <VAR> %%DEFAULT%%
              - Reset VAR's default value with '%%DEFAULT%%' magic string

            > set <VAR> "file:///path/to/file"
              - Bind VAR's value to a local file content

            > set <VAR> +
              - Open VAR's value in text editor. This is useful to edit
              values with multiple lines

            > set <VAR> + <LINE>
              - Add LINE to the end of VAR's value

            > set <VAR> + "file:///path/to/file"
              - Re-bind VAR to a local file path.
              Even if path doesn't exist, the setting will take the value of
              the file if it founds it. Otherwise, previous buffer value is
              kept as long as the file path is unreachable

        Defining HTTP Headers:
            You can define custom http request header fields by hand.

            Settings starting with 'HTTP_' are automagically treated as
            HTTP Request Headers values.

            By default, only the "User-Agent" Header is defined. It is bound
            by default to a local file containing common HTTP User Agents.
            (`help set HTTP_USER_AGENT`)

            * Examples:
            > set HTTP_ACCEPT_LANGUAGE "en-CA"
              - Define "Accept-Language" http request header field.
            > set HTTP_ACCEPT_LANGUAGE None
              - Remove HTTP_ACCEPT_LANGUAGE header with magic value 'None'.
        """
        # `set [<PATTERN>]` display concerned settings list
        if len(argv) < 3:
            print(session.Conf((argv+[""])[1]))

        # buffer edit mode
        elif argv[2] == "+":
            # `set <VAR> +`: use $EDITOR as buffer viewer in file mode
            if len(argv) == 3:
                # get a buffer obj from setting's raw buffer value
                file_name = argv[1].upper()
                file_ext = "txt"
                setting_obj = session.Conf[argv[1]](call=False)
                if isinstance(setting_obj, datatypes.PhpCode):
                    file_ext = "php"
                elif isinstance(setting_obj, datatypes.ShellCmd):
                    file_ext = "sh"
                buffer = Path(filename="%s.%s" % (file_name, file_ext))
                buffer.write(session.Conf[argv[1]].buffer)
                # try to edit it through $EDITOR, and update it
                # if it has been modified.
                if buffer.edit():
                    session.Conf[argv[1]] = buffer.read()
            # `set <VAR> + "value"`: add value on setting possible choices
            else:
                session.Conf[argv[1]] += " ".join(argv[3:])
        # `set <VAR> "value"`: just change VAR's "value"
        else:
            session.Conf[argv[1]] = " ".join(argv[2:])

    ################
    # COMMAND: env #
    @staticmethod
    def complete_env(text, *_):
        """Use env vars as `env` completers (case insensitive)"""
        result = []
        for key in session.Env:
            if key.startswith(text.upper()):
                result.append(key)
        return result

    @staticmethod
    def do_env(argv):
        """Environment variables handler

        SYNOPSIS:
            env [<NAME> ["<VALUE>"|None]]

        DESCRIPTION:
            The phpsploit environment variables are created once a
            remote server tunnel is opened through the interface.
            These variables are used by the core and a few plugins in
            order to interract with the werbserver's current state.

            > env
            - Display all current env vars

            > env <STRING>
            - Display all env vars whose name starts with STRING.

            > env <NAME> "<VALUE>"
            - Set NAME env variable's value to VALUE.

            > env <NAME> None
            - Remove NAME environment variable.

        CASE STUDY:
            The `PWD` environment variable changes each time the `cd`
            command is used. It contains the current directory path of
            the session. When a remote server exploitation session starts,
            it is defaultly set to the server's HOME directory if,
            available, otherwise, it is set to the root web directory.
            This environment variable may be manually changed by using the
            `env PWD "/other/path"`, but it is generally not recommended
            since it can broke some plugins if the value is not a remote
            accessible absolute path.

        BEHAVIOR:
            - At framework start, the env vars array is empty.

            - Env vars array is filled once a remote server shell is
            started through the phpsploit framework.

            - Some envionment variables, such as `PWD` and `WEB_ROOT` are
            crucial for remote session consistency. Be careful before
            manually editing them.

            - Plugins that need persistent server based variables may and
            must use env vars. For example, the `mysql` plugin creates a
            `MYSQL_CRED` environment variable that contains remote
            database connection credentials when using `mysql connect`,
            it allows the plugin to not require setting user/pass/serv
            informations on each remote sql command.

            - Unlike settings, env vars do not provide dynamic random
            values. Setting a value is simply interpreted as a string,
            apart for the special "None" value, which deletes the variable.
        """
        if len(argv) < 3:
            # `env [<PATTERN>]` display concerned settings list
            print(session.Env((argv + [""])[1]))
        else:
            # `env <NAME> <VALUE>`
            session.Env[argv[1]] = " ".join(argv[2:])

    ##################
    # COMMAND: alias #
    @staticmethod
    def complete_alias(text, *_):
        """autocompletion for `alias` command"""
        result = []
        for key in session.Alias.keys():
            if key.startswith(text):
                result.append(key)
        return result

    @staticmethod
    def do_alias(argv):
        """Define command aliases

        SYNOPSIS:
            alias [<NAME> ["<VALUE>"|None]]

        DESCRIPTION:
            Command aliases can be defined in order to ease phpsploit
            shell experience.
            Once defined, an alias can be used as if it was a standard
            command, and it's value is interpreted, then suffixed with
            arguments passed to the command line (if any).

            NOTE: This core command works like the unix bash `alias`
            command.

            > alias
              - Display all current command aliases.

            > alias <NAME>
              - Display aliases whose name starts with NAME.

            > alias <NAME> <VALUE>
              - Set NAME alias to the given VALUE.

            > alias <NAME> None
              - Unset NAME command alias.

        BEHAVIOR:
            - Unlike settings, aliases do not provide dynamic random
            values. Setting a value is simply interpreted as a string,
            apart for the special "None" value, which removes the variable.
        """
        if len(argv) < 3:
            # `alias [<PATTERN>]` display concerned settings list
            print(session.Alias((argv+[""])[1]))
        else:
            # `alias <NAME> <VALUE>`
            session.Alias[argv[1]] = " ".join(argv[2:])


    ##################
    # COMMAND: bind #
    def complete_bind(self, text, *ignored):
        """autocompletion for `bind` command"""
        result = super().completenames(text, ignored)
        result = [x for x in result if x != "bind"]
        if tunnel:
            result += plugins.keys()
        return [x for x in list(set(result)) if x.startswith(text)]

    def do_bind(self, argv):
        """attach a command to prompt

        SYNOPSIS:
            bind [<COMMAND>]

        DESCRIPTION:
            Bind phpsploit prompt to COMMAND.
            Every line executed will then be executed as if it was
            the arguments of COMMAND.
            This is useful for plugins like `run` or `mysql`, when you
            are working from them and don't want to re-type the plugin
            name again and again ..

            NOTE: press Ctrl-D or type exit to 'unbind' from current command.

        DEMO:
            phpsploit(127.0.0.1) > run type ls
            ls is /bin/ls
            phpsploit(127.0.0.1) > type ls
            [-] Unknown Command: type
            phpsploit(127.0.0.1) > bind run
            [-] Type exit to leave binded 'run' subshell
            # now shell is bound to `run`, so we just need to execute `type ls`
            phpsploit(127.0.0.1) #run > type ls
            ls is /bin/ls
        """
        if len(argv) != 2 or argv[1] not in self.complete_bind("", ""):
            self.interpret("help bind")
        else:
            self.bind_command = argv[1]
            print("[-] Type exit to leave bound %r subshell" % argv[1])


    ####################
    # COMMAND: backlog #
    def do_backlog(self, argv):
        """open last command output in text editor

        SYNOPSIS:
            backlog [--save <FILE>]

        DESCRIPTION:
            Open last command output with text EDITOR (`help set EDITOR`).
            Ansi terminal colors are automatically stripped from buffer.

        OPTIONS:
            --save <FILE>
                Write previous command's output to the given
                file instead of opening it with $EDITOR.
        """
        if len(argv) == 1:
            backlog = Path()
            backlog.write(self.stdout.backlog, bin_mode=True)
            backlog.edit()
        elif len(argv) == 3 and argv[1] == "--save":
            Path(argv[2]).write(self.stdout.backlog)
        else:
            self.interpret("help backlog")


    #################
    # COMMAND: help #
    def do_help(self, argv):
        """Show commands help

        SYNOPSIS:
            help [<COMMAND>]
            help set <SETTING>

        DESCRIPTION:
            Display help message for any command, including plugins.

            - Without arguments, the whole available commands, sorted
              by category, are displayed including a summary line for
              each one.

            - For detailed help, the command should be given as
              argument.

        EXAMPLES:
            > help
              - Display the full help, sorted by category
            > help exit
              - Display the help for the `exit` command
            > help set BACKDOOR
              - Display help about the "BACKDOOR" setting
        """
        # If more than 1 argument, help to help !
        if len(argv) > 2 and argv[1] != "set":
            return self.interpret('help help')

        # collect the command list from current shell
        core_commands = self.get_names(self, "do_")

        def get_doc(cmd):
            """return the docstring lines list of specific command"""
            # try to get the doc from the plugin method
            doc = None
            if cmd in plugins:
                doc = plugins[cmd].help
            elif hasattr(self, "do_" + cmd):
                doc = getattr(self, "do_" + cmd).__doc__
            if not doc:
                doc = ""
            return doc.strip().splitlines()

        def get_description(doc_lines):
            """return the command description (1st docstring line)"""
            if doc_lines:
                return doc_lines[0].strip()
            return colorize("%Yellow", "No description")

        def doc_help(doc_lines):
            """print the formated command's docstring"""
            # reject empty docstrings (description + empty line)
            if len(doc_lines) < 2:
                return False
            doc_lines.pop(0)  # remove the description line
            while not doc_lines[0].strip():
                doc_lines.pop(0)  # remove heading empty lines

            # remove junk leading spaces (due to python indentation)
            trash = len(doc_lines[0]) - len(doc_lines[0].lstrip())
            doc_lines = [line[trash:].rstrip() for line in doc_lines]

            # hilight lines with no leading spaces (man style)
            result = str()
            for line in doc_lines:
                if line == line.lstrip():
                    line = colorize("%BoldWhite", line)
                elif line.startswith("    * "):
                    line = colorize("    * ", "%Yellow", line[6:])
                elif line.startswith("    > "):
                    line = colorize("    > ", "%Cyan", line[6:])
                elif line.startswith("    # "):
                    line = colorize("%Dim", line)
                elif line.startswith("    -") and line[5] != " ":
                    line = colorize("%Green", line)
                result += line + "\n"

            print(result)

        # get full help on a single command
        if len(argv) == 2:
            doc = get_doc(argv[1])
            # if the given argument is not a command, return nohelp err
            if not doc:
                if argv[1] in session.Alias:
                    return self.interpret("alias %s" % argv[1])
                print(self.nohelp % argv[1])
                return False

            # print the heading help line, which contain description
            print("\n[*] " + argv[1] + ": " + get_description(doc) + "\n")

            # call the help_<command> method, otherwise, print it's docstring
            help_method = getattr(self, "help_" + argv[1], None)
            if callable(help_method):
                getattr(self, 'help_' + argv[1])()
                return True
            return doc_help(doc)
        # get help about settings (e.g.: `help set BACKDOOR`)
        if len(argv) == 3 and argv[1] == "set":
            setting = argv[2]
            try:
                doc = getattr(session.Conf, setting).docstring
            except KeyError:
                print("[-] %s: No such configuration setting" % setting)
                return
            print("\n[*] Help for '%s' setting\n" % setting)
            doc_help(doc.splitlines())
            return

        # display the whole list of commands, with their description line

        # set maxLength to the longest command name, and at least 13
        maxLength = max(13, len(max(core_commands, key=len)))

        help = [('Core Commands', core_commands)]

        # adds plugin category if we are connected to target
        if tunnel:
            for category in plugins.categories():
                items = [p for p in plugins.values() if p.category == category]
                items = [p.name for p in items]
                # rescale maxLength in case of longer plugin names
                maxLength = max(maxLength, len(max(items, key=len)))
                help += [(category + ' Plugins', items)]

        # Settle maxLength if there are command aliases
        aliases = list(session.Alias.keys())
        if aliases:
            maxLength = max(maxLength, len(max(aliases, key=len)))
            help += [("Command Aliases", aliases)]

        # print commands help, sorted by groups
        cmdColumn = ' ' * (maxLength - 5)
        for groupName, groupCommands in help:

            # display group (category) header block
            underLine = '=' * len(groupName)
            if groupName == "Command Aliases":
                print("\n" + groupName + "\n" + underLine + "\n" +
                      '    Alias  ' + cmdColumn + 'Value      ' + "\n" +
                      '    -----  ' + cmdColumn + '-----      ' + "\n")
            else:
                print("\n" + groupName + "\n" + underLine + "\n" +
                      '    Command' + cmdColumn + 'Description' + "\n" +
                      '    -------' + cmdColumn + '-----------' + "\n")

            # display formated command/description pairs
            groupCommands.sort()
            for cmdName in groupCommands:
                spaceFill = ' ' * (maxLength - len(cmdName) + 2)
                if groupName == "Command Aliases":
                    description = session.Alias[cmdName]
                else:
                    description = get_description(get_doc(cmdName))
                print('    ' + cmdName + spaceFill + description)
            print('')

    # pylint: disable=invalid-name
    @staticmethod
    def except_OSError(exception):
        """Fix OSError args, removing errno, and adding filename"""
        if isinstance(exception.errno, int):
            exception.args = (exception.strerror,)
        if exception.filename is not None:
            exception.args += ("«{}»".format(exception.filename),)
        return exception


def debug_cmdrepr(argv):
    """Returns a nice representation of given command arguments
    """
    cmdrepr = []
    for arg in argv:
        if not isinstance(arg, str):
            continue
        argrepr = repr(arg)
        sep = argrepr[0], argrepr[-1]
        argrepr = argrepr[1:-1].join(colorize("%DimCyan", "%Reset"))
        cmdrepr.append(sep[0] + argrepr + sep[1])
    args = " ".join(cmdrepr)
    return colorize("%BoldCyan", "CMD(", "%Reset", args, "%BoldCyan", ")")
