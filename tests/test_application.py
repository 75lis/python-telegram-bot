#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2022
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""The integration of persistence into the application is tested in test_persistence_integration.
"""
import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from queue import Queue

import pytest

from telegram import Bot, Message, User, MessageEntity, Chat
from telegram.ext import (
    JobQueue,
    CallbackContext,
    ApplicationBuilder,
    Application,
    ContextTypes,
    PicklePersistence,
    Updater,
    filters,
    MessageHandler,
    Handler,
    ApplicationHandlerStop,
    CommandHandler,
    TypeHandler,
    Defaults,
)

from telegram.error import TelegramError
from telegram.warnings import PTBUserWarning

from tests.conftest import make_message_update, PROJECT_ROOT_PATH


class CustomContext(CallbackContext):
    pass


class TestApplication:
    """The integration of persistence into the application is tested in
    test_persistence_integration.
    """

    message_update = make_message_update(message='Text')
    received = None
    count = 0

    @pytest.fixture(autouse=True, name='reset')
    def reset_fixture(self):
        self.reset()

    def reset(self):
        self.received = None
        self.count = 0

    async def error_handler_context(self, update, context):
        self.received = context.error.message

    async def error_handler_raise_error(self, update, context):
        raise Exception('Failing bigly')

    async def callback_increase_count(self, update, context):
        self.count += 1

    def callback_set_count(self, count, sleep: float = None):
        async def callback(update, context):
            if sleep:
                await asyncio.sleep(sleep)
            self.count = count

        return callback

    def callback_raise_error(self, error_message: str):
        async def callback(update, context):
            raise TelegramError(error_message)

        return callback

    async def callback_received(self, update, context):
        self.received = update.message

    async def callback_context(self, update, context):
        if (
            isinstance(context, CallbackContext)
            and isinstance(context.bot, Bot)
            and isinstance(context.update_queue, Queue)
            and isinstance(context.job_queue, JobQueue)
            and isinstance(context.error, TelegramError)
        ):
            self.received = context.error.message

    def test_slot_behaviour(self, bot, mro_slots):
        app = ApplicationBuilder().bot(bot).build()
        for at in app.__slots__:
            at = f"_Application{at}" if at.startswith('__') and not at.endswith('__') else at
            assert getattr(app, at, 'err') != 'err', f"got extra slot '{at}'"
        assert len(mro_slots(app)) == len(set(mro_slots(app))), "duplicate slot"

    def test_manual_init_warning(self, recwarn, updater):
        Application(
            bot=None,
            update_queue=None,
            job_queue=None,
            persistence=None,
            context_types=ContextTypes(),
            updater=updater,
            concurrent_updates=False,
        )
        assert len(recwarn) == 1
        assert (
            str(recwarn[-1].message)
            == '`Application` instances should be built via the `ApplicationBuilder`.'
        )
        assert recwarn[0].filename == __file__, "stacklevel is incorrect!"

    @pytest.mark.parametrize(
        'concurrent_updates, expected', [(0, 0), (4, 4), (False, 0), (True, 4096)]
    )
    @pytest.mark.filterwarnings("ignore: `Application` instances should")
    def test_init(self, bot, concurrent_updates, expected):
        update_queue = asyncio.Queue()
        job_queue = JobQueue()
        persistence = PicklePersistence('file_path')
        context_types = ContextTypes()
        updater = Updater(bot=bot, update_queue=update_queue)
        app = Application(
            bot=bot,
            update_queue=update_queue,
            job_queue=job_queue,
            persistence=persistence,
            context_types=context_types,
            updater=updater,
            concurrent_updates=concurrent_updates,
        )
        assert app.bot is bot
        assert app.update_queue is update_queue
        assert app.job_queue is job_queue
        assert app.persistence is persistence
        assert app.context_types is context_types
        assert app.updater is updater
        assert app.update_queue is updater.update_queue
        assert app.bot is updater.bot
        assert app.concurrent_updates == expected

        # These should be done by the builder
        assert app.persistence.bot is None
        with pytest.raises(RuntimeError, match='No application was set'):
            app.job_queue.application

        assert isinstance(app.bot_data, dict)
        assert isinstance(app.chat_data[1], dict)
        assert isinstance(app.user_data[1], dict)

        with pytest.raises(ValueError, match='must be a non-negative'):
            Application(
                bot=bot,
                update_queue=update_queue,
                job_queue=job_queue,
                persistence=persistence,
                context_types=context_types,
                updater=updater,
                concurrent_updates=-1,
            )

    def test_custom_context_init(self, bot):
        cc = ContextTypes(
            context=CustomContext,
            user_data=int,
            chat_data=float,
            bot_data=complex,
        )

        application = ApplicationBuilder().bot(bot).context_types(cc).build()

        assert isinstance(application.user_data[1], int)
        assert isinstance(application.chat_data[1], float)
        assert isinstance(application.bot_data, complex)

    @pytest.mark.asyncio
    async def test_initialize(self, bot, monkeypatch):
        """Initialization of persistence is tested eslewhere"""
        # TODO: do this!
        self.test_flag = set()

        async def initialize_bot(*args, **kwargs):
            self.test_flag.add('bot')

        async def initialize_updater(*args, **kwargs):
            self.test_flag.add('updater')

        monkeypatch.setattr(Bot, 'initialize', initialize_bot)
        monkeypatch.setattr(Updater, 'initialize', initialize_updater)

        await ApplicationBuilder().token(bot.token).build().initialize()
        assert self.test_flag == {'bot', 'updater'}

    @pytest.mark.asyncio
    async def test_shutdown(self, bot, monkeypatch):
        """Studown of persistence is tested eslewhere"""
        # TODO: do this!
        self.test_flag = set()

        async def shutdown_bot(*args, **kwargs):
            self.test_flag.add('bot')

        async def shutdown_updater(*args, **kwargs):
            self.test_flag.add('updater')

        monkeypatch.setattr(Bot, 'shutdown', shutdown_bot)
        monkeypatch.setattr(Updater, 'shutdown', shutdown_updater)

        async with ApplicationBuilder().token(bot.token).build():
            pass
        assert self.test_flag == {'bot', 'updater'}

    @pytest.mark.asyncio
    async def test_multiple_inits_and_shutdowns(self, app, monkeypatch):
        self.received = defaultdict(int)

        async def initialize(*args, **kargs):
            self.received['init'] += 1

        async def shutdown(*args, **kwargs):
            self.received['shutdown'] += 1

        monkeypatch.setattr(app.bot, 'initialize', initialize)
        monkeypatch.setattr(app.bot, 'shutdown', shutdown)

        await app.initialize()
        await app.initialize()
        await app.initialize()
        await app.shutdown()
        await app.shutdown()
        await app.shutdown()

        # 2 instead of 1 since `Updater.initialize` also calls bot.init/shutdown
        assert self.received['init'] == 2
        assert self.received['shutdown'] == 2

    @pytest.mark.asyncio
    async def test_multiple_init_cycles(self, app):
        # nothing really to assert - this should just not fail
        async with app:
            await app.bot.get_me()
        async with app:
            await app.bot.get_me()

    @pytest.mark.asyncio
    async def test_start_without_initialize(self, app):
        with pytest.raises(RuntimeError, match='not initialized'):
            await app.start()

    @pytest.mark.asyncio
    async def test_shutdown_while_running(self, app):
        async with app:
            await app.start()
            with pytest.raises(RuntimeError, match='still running'):
                await app.shutdown()
            await app.stop()

    @pytest.mark.asyncio
    async def test_start_not_running_after_failure(self, app):
        class Event(asyncio.Event):
            def set(self) -> None:
                raise Exception('Test Exception')

        async with app:
            with pytest.raises(Exception, match='Test Exception'):
                await app.start(ready=Event())
            assert app.running is False

    @pytest.mark.asyncio
    async def test_context_manager(self, monkeypatch, app):
        self.test_flag = set()

        async def initialize(*args, **kwargs):
            self.test_flag.add('initialize')

        async def shutdown(*args, **kwargs):
            self.test_flag.add('stop')

        monkeypatch.setattr(Application, 'initialize', initialize)
        monkeypatch.setattr(Application, 'shutdown', shutdown)

        async with app:
            pass

        assert self.test_flag == {'initialize', 'stop'}

    @pytest.mark.asyncio
    async def test_context_manager_exception_on_init(self, monkeypatch, app):
        async def initialize(*args, **kwargs):
            raise RuntimeError('initialize')

        async def shutdown(*args):
            self.test_flag = 'stop'

        monkeypatch.setattr(Application, 'initialize', initialize)
        monkeypatch.setattr(Application, 'shutdown', shutdown)

        with pytest.raises(RuntimeError, match='initialize'):
            async with app:
                pass

        assert self.test_flag == 'stop'

    @pytest.mark.parametrize("data", ["chat_data", "user_data"])
    def test_chat_user_data_read_only(self, app, data):
        read_only_data = getattr(app, data)
        writable_data = getattr(app, f"_{data}")
        writable_data[123] = 321
        assert read_only_data == writable_data
        with pytest.raises(TypeError):
            read_only_data[111] = 123

    def test_builder(self, app):
        builder_1 = app.builder()
        builder_2 = app.builder()
        assert isinstance(builder_1, ApplicationBuilder)
        assert isinstance(builder_2, ApplicationBuilder)
        assert builder_1 is not builder_2

        # Make sure that setting a token doesn't raise an exception
        # i.e. check that the builders are "empty"/new
        builder_1.token(app.bot.token)
        builder_2.token(app.bot.token)

    @pytest.mark.asyncio
    async def test_start_stop_processing_updates(self, app):
        # TODO: repeat a similar test for create_task, persistence processing and job queue
        async def callback(u, c):
            self.received = u

        assert not app.running
        assert not app.updater.running
        app.add_handler(TypeHandler(object, callback))

        await app.update_queue.put(1)
        await asyncio.sleep(0.05)
        assert not app.update_queue.empty()
        assert self.received is None

        async with app:
            await app.start()
            assert app.running
            assert not app.updater.running
            await asyncio.sleep(0.05)
            assert app.update_queue.empty()
            assert self.received == 1

            await app.stop()
            assert not app.running
            assert not app.updater.running
            await app.update_queue.put(2)
            await asyncio.sleep(0.05)
            assert not app.update_queue.empty()
            assert self.received != 2
            assert self.received == 1

    @pytest.mark.asyncio
    async def test_error_start_stop_twice(self, app):
        async with app:
            await app.start()
            assert app.running
            with pytest.raises(RuntimeError, match='already running'):
                await app.start()

            await app.stop()
            assert not app.running
            with pytest.raises(RuntimeError, match='not running'):
                await app.stop()

    @pytest.mark.asyncio
    async def test_one_context_per_update(self, app):
        self.received = None

        async def one(update, context):
            self.received = context

        def two(update, context):
            if update.message.text == 'test':
                if context is not self.received:
                    pytest.fail('Expected same context object, got different')
            else:
                if context is self.received:
                    print(context, self.received)
                    pytest.fail('First handler was wrongly called')

        app.add_handler(MessageHandler(filters.Regex('test'), one), group=1)
        app.add_handler(MessageHandler(filters.ALL, two), group=2)
        u = make_message_update(message='test')
        await app.process_update(u)
        self.received = None
        u.message.text = 'something'
        await app.process_update(u)

    def test_add_handler_errors(self, app):
        handler = 'not a handler'
        with pytest.raises(TypeError, match='handler is not an instance of'):
            app.add_handler(handler)

        handler = MessageHandler(filters.PHOTO, self.callback_set_count(1))
        with pytest.raises(TypeError, match='group is not int'):
            app.add_handler(handler, 'one')

    @pytest.mark.asyncio
    async def test_add_remove_handler(self, app):
        handler = MessageHandler(filters.ALL, self.callback_increase_count)
        app.add_handler(handler)

        async with app:
            await app.start()
            await app.update_queue.put(self.message_update)
            await asyncio.sleep(0.05)
            assert self.count == 1
            app.remove_handler(handler)
            await app.update_queue.put(self.message_update)
            assert self.count == 1
            await app.stop()

    @pytest.mark.asyncio
    async def test_add_remove_handler_non_default_group(self, app):
        handler = MessageHandler(filters.ALL, self.callback_increase_count)
        app.add_handler(handler, group=2)
        with pytest.raises(KeyError):
            app.remove_handler(handler)
        app.remove_handler(handler, group=2)

    #
    @pytest.mark.asyncio
    async def test_handler_order_in_group(self, app):
        app.add_handler(MessageHandler(filters.PHOTO, self.callback_set_count(1)))
        app.add_handler(MessageHandler(filters.ALL, self.callback_set_count(2)))
        app.add_handler(MessageHandler(filters.TEXT, self.callback_set_count(3)))
        async with app:
            await app.start()
            await app.update_queue.put(self.message_update)
            await asyncio.sleep(0.05)
            assert self.count == 2
            await app.stop()

    @pytest.mark.asyncio
    async def test_groups(self, app):
        app.add_handler(MessageHandler(filters.ALL, self.callback_increase_count))
        app.add_handler(MessageHandler(filters.ALL, self.callback_increase_count), group=2)
        app.add_handler(MessageHandler(filters.ALL, self.callback_increase_count), group=-1)

        async with app:
            await app.start()
            await app.update_queue.put(self.message_update)
            await asyncio.sleep(0.05)
            assert self.count == 3
            await app.stop()

    @pytest.mark.asyncio
    async def test_add_handlers(self, app):
        """Tests both add_handler & add_handlers together & confirms the correct insertion
        order"""
        msg_handler_set_count = MessageHandler(filters.TEXT, self.callback_set_count(1))
        msg_handler_inc_count = MessageHandler(filters.PHOTO, self.callback_increase_count)

        app.add_handler(msg_handler_set_count, 1)
        app.add_handlers((msg_handler_inc_count, msg_handler_inc_count), 1)

        photo_update = make_message_update(message=Message(2, None, None, photo=True))

        async with app:
            await app.start()
            # Putting updates in the queue calls the callback
            await app.update_queue.put(self.message_update)
            await app.update_queue.put(photo_update)
            await asyncio.sleep(0.05)  # sleep is required otherwise there is random behaviour

            # Test if handler was added to correct group with correct order-
            assert (
                self.count == 2
                and len(app.handlers[1]) == 3
                and app.handlers[1][0] is msg_handler_set_count
            )

            # Now lets test add_handlers when `handlers` is a dict-
            voice_filter_handler_to_check = MessageHandler(
                filters.VOICE, self.callback_increase_count
            )
            app.add_handlers(
                handlers={
                    1: [
                        MessageHandler(filters.USER, self.callback_increase_count),
                        voice_filter_handler_to_check,
                    ],
                    -1: [MessageHandler(filters.CAPTION, self.callback_set_count(2))],
                }
            )

            user_update = make_message_update(
                message=Message(3, None, None, from_user=User(1, 's', True))
            )
            voice_update = make_message_update(message=Message(4, None, None, voice=True))
            await app.update_queue.put(user_update)
            await app.update_queue.put(voice_update)
            await asyncio.sleep(0.05)

            assert (
                self.count == 4
                and len(app.handlers[1]) == 5
                and app.handlers[1][-1] is voice_filter_handler_to_check
            )

            await app.update_queue.put(
                make_message_update(message=Message(5, None, None, caption='cap'))
            )
            await asyncio.sleep(0.05)

            assert self.count == 2 and len(app.handlers[-1]) == 1

            # Now lets test the errors which can be produced-
            with pytest.raises(ValueError, match="The `group` argument"):
                app.add_handlers({2: [msg_handler_set_count]}, group=0)
            with pytest.raises(ValueError, match="Handlers for group 3"):
                app.add_handlers({3: msg_handler_set_count})
            with pytest.raises(ValueError, match="The `handlers` argument must be a sequence"):
                app.add_handlers({msg_handler_set_count})

            await app.stop()

    @pytest.mark.asyncio
    async def test_check_update(self, app):
        class TestHandler(Handler):
            def check_update(_, update: object):
                self.received = object()

            def handle_update(
                _,
                update,
                application,
                check_result,
                context,
            ):
                assert application is app
                assert check_result is not self.received

        async with app:
            app.add_handler(TestHandler('callback'))
            await app.start()
            await app.update_queue.put(object())
            await asyncio.sleep(0.05)
            await app.stop()

    @pytest.mark.asyncio
    async def test_flow_stop(self, app, bot):
        passed = []

        async def start1(b, u):
            passed.append('start1')
            raise ApplicationHandlerStop

        async def start2(b, u):
            passed.append('start2')

        async def start3(b, u):
            passed.append('start3')

        update = make_message_update(
            message=Message(
                1,
                None,
                None,
                None,
                text='/start',
                entities=[
                    MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=len('/start'))
                ],
                bot=bot,
            ),
        )

        # If ApplicationHandlerStop raised handlers in other groups should not be called.
        passed = []
        app.add_handler(CommandHandler('start', start1), 1)
        app.add_handler(CommandHandler('start', start3), 1)
        app.add_handler(CommandHandler('start', start2), 2)
        await app.process_update(update)
        assert passed == ['start1']

    @pytest.mark.asyncio
    async def test_flow_stop_by_error_handler(self, app, bot):
        passed = []
        exception = Exception('General excepition')

        async def start1(b, u):
            passed.append('start1')
            raise exception

        async def start2(b, u):
            passed.append('start2')

        async def start3(b, u):
            passed.append('start3')

        async def error(u, c):
            passed.append('error')
            passed.append(c.error)
            raise ApplicationHandlerStop

        # If ApplicationHandlerStop raised handlers in other groups should not be called.
        passed = []
        app.add_error_handler(error)
        app.add_handler(TypeHandler(object, start1), 1)
        app.add_handler(TypeHandler(object, start2), 1)
        app.add_handler(TypeHandler(object, start3), 2)
        await app.process_update(1)
        assert passed == ['start1', 'error', exception]

    @pytest.mark.asyncio
    async def test_error_in_handler_part_1(self, app):
        app.add_handler(
            MessageHandler(
                filters.ALL,
                self.callback_raise_error(error_message=self.message_update.message.text),
            )
        )
        app.add_handler(MessageHandler(filters.ALL, self.callback_set_count(42)), group=1)
        app.add_error_handler(self.error_handler_context)

        async with app:
            await app.start()
            await app.update_queue.put(self.message_update)
            await asyncio.sleep(0.05)
            await app.stop()

        assert self.received == self.message_update.message.text
        # Higher groups should still be called
        assert self.count == 42

    @pytest.mark.asyncio
    async def test_error_in_handler_part_2(self, app, bot):
        passed = []
        err = Exception('General exception')

        async def start1(u, c):
            passed.append('start1')
            raise err

        async def start2(u, c):
            passed.append('start2')

        async def start3(u, c):
            passed.append('start3')

        async def error(u, c):
            passed.append('error')
            passed.append(c.error)

        update = make_message_update(
            message=Message(
                1,
                None,
                None,
                None,
                text='/start',
                entities=[
                    MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=len('/start'))
                ],
                bot=bot,
            ),
        )

        # If an unhandled exception was caught, no further handlers from the same group should be
        # called. Also, the error handler should be called and receive the exception
        passed = []
        app.add_handler(CommandHandler('start', start1), 1)
        app.add_handler(CommandHandler('start', start2), 1)
        app.add_handler(CommandHandler('start', start3), 2)
        app.add_error_handler(error)
        await app.process_update(update)
        assert passed == ['start1', 'error', err, 'start3']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('block', (True, False))
    async def test_error_handler(self, app, block):
        app.add_error_handler(self.error_handler_context)
        app.add_handler(TypeHandler(object, self.callback_raise_error('TestError'), block=block))

        async with app:
            await app.start()
            await app.update_queue.put(1)
            await asyncio.sleep(0.05)
            assert self.received == 'TestError'

            # Remove handler
            app.remove_error_handler(self.error_handler_context)
            self.reset()

            await app.update_queue.put(1)
            await asyncio.sleep(0.05)
            assert self.received is None

            await app.stop()

    def test_double_add_error_handler(self, app, caplog):
        app.add_error_handler(self.error_handler_context)
        with caplog.at_level(logging.DEBUG):
            app.add_error_handler(self.error_handler_context)
            assert len(caplog.records) == 1
            assert caplog.records[-1].getMessage().startswith('The callback is already registered')

    @pytest.mark.asyncio
    async def test_error_handler_that_raises_errors(self, app, caplog):
        """Make sure that errors raised in error handlers don't break the main loop of the
        application
        """
        handler_raise_error = TypeHandler(
            int, self.callback_raise_error(error_message='TestError')
        )
        handler_increase_count = TypeHandler(str, self.callback_increase_count)

        app.add_error_handler(self.error_handler_raise_error)
        app.add_handler(handler_raise_error)
        app.add_handler(handler_increase_count)

        with caplog.at_level(logging.ERROR):
            async with app:
                await app.start()
                await app.update_queue.put(1)
                await asyncio.sleep(0.05)
                assert self.count == 0
                assert self.received is None
                assert len(caplog.records) > 0
                log_messages = (record.getMessage() for record in caplog.records)
                assert any(
                    'uncaught error was raised while handling the error with an error_handler'
                    in message
                    for message in log_messages
                )

                await app.update_queue.put('1')
                self.received = None
                caplog.clear()
                await asyncio.sleep(0.05)
                assert self.count == 1
                assert self.received is None
                assert not caplog.records

                await app.stop()

    @pytest.mark.asyncio
    async def test_custom_context_error_handler(self, bot):
        async def error_handler(_, context):
            self.received = (
                type(context),
                type(context.user_data),
                type(context.chat_data),
                type(context.bot_data),
            )

        application = (
            ApplicationBuilder()
            .bot(bot)
            .context_types(
                ContextTypes(
                    context=CustomContext, bot_data=int, user_data=float, chat_data=complex
                )
            )
            .build()
        )
        application.add_error_handler(error_handler)
        application.add_handler(
            MessageHandler(filters.ALL, self.callback_raise_error('TestError'))
        )

        await application.process_update(self.message_update)
        await asyncio.sleep(0.05)
        assert self.received == (CustomContext, float, complex, int)

    @pytest.mark.asyncio
    async def test_custom_context_handler_callback(self, bot):
        def callback(_, context):
            self.received = (
                type(context),
                type(context.user_data),
                type(context.chat_data),
                type(context.bot_data),
            )

        application = (
            ApplicationBuilder()
            .bot(bot)
            .context_types(
                ContextTypes(
                    context=CustomContext, bot_data=int, user_data=float, chat_data=complex
                )
            )
            .build()
        )
        application.add_handler(MessageHandler(filters.ALL, callback))

        await application.process_update(self.message_update)
        await asyncio.sleep(0.05)
        assert self.received == (CustomContext, float, complex, int)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'check,expected',
        [(True, True), (None, False), (False, False), ({}, True), ('', True), ('check', True)],
    )
    async def test_check_update_handling(self, app, check, expected):
        class MyHandler(Handler):
            def check_update(self, update: object):
                return check

            async def handle_update(
                _,
                update,
                application,
                check_result,
                context,
            ):
                await super().handle_update(
                    update=update,
                    application=application,
                    check_result=check_result,
                    context=context,
                )
                self.received = check_result

        app.add_handler(MyHandler(self.callback_increase_count))
        await app.process_update(1)
        assert self.count == (1 if expected else 0)
        if expected:
            assert self.received == check
        else:
            assert self.received is None

    @pytest.mark.asyncio
    async def test_non_blocking_handler(self, app):
        event = asyncio.Event()

        async def callback(update, context):
            await event.wait()
            self.count = 42

        app.add_handler(TypeHandler(object, callback, block=False))
        app.add_handler(TypeHandler(object, self.callback_increase_count), group=1)

        async with app:
            await app.start()
            await app.update_queue.put(1)
            task = asyncio.create_task(app.stop())
            await asyncio.sleep(0.05)
            assert self.count == 1
            # Make sure that app stops only once all non blocking callbacks are done
            assert not task.done()
            event.set()
            await asyncio.sleep(0.05)
            assert self.count == 42
            assert task.done()

    @pytest.mark.asyncio
    async def test_non_blocking_handler_applicationhandlerstop(self, app, recwarn):
        async def callback(update, context):
            raise ApplicationHandlerStop

        app.add_handler(TypeHandler(object, callback, block=False))

        async with app:
            await app.start()
            await app.update_queue.put(1)
            await asyncio.sleep(0.05)
            await app.stop()

        assert len(recwarn) == 1
        assert recwarn[0].category is PTBUserWarning
        assert (
            str(recwarn[0].message)
            == 'ApplicationHandlerStop is not supported with asynchronously running handlers.'
        )
        assert (
            Path(recwarn[0].filename) == PROJECT_ROOT_PATH / 'telegram' / 'ext' / '_application.py'
        ), "incorrect stacklevel!"

    @pytest.mark.asyncio
    async def test_non_blocking_no_error_handler(self, app, caplog):
        app.add_handler(TypeHandler(object, self.callback_raise_error, block=False))

        with caplog.at_level(logging.ERROR):
            async with app:
                await app.start()
                await app.update_queue.put(1)
                await asyncio.sleep(0.05)
                assert len(caplog.records) == 1
                assert (
                    caplog.records[-1].getMessage().startswith('No error handlers are registered')
                )
                await app.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('handler_block', (True, False))
    async def test_non_blocking_error_handler(self, app, handler_block):
        event = asyncio.Event()

        async def async_error_handler(update, context):
            await event.wait()
            self.received = 'done'

        async def normal_error_handler(update, context):
            self.count = 42

        app.add_error_handler(async_error_handler, block=False)
        app.add_error_handler(normal_error_handler)
        app.add_handler(TypeHandler(object, self.callback_raise_error, block=handler_block))

        async with app:
            await app.start()
            await app.update_queue.put(self.message_update)
            task = asyncio.create_task(app.stop())
            await asyncio.sleep(0.05)
            assert self.count == 42
            assert self.received is None
            event.set()
            await asyncio.sleep(0.05)
            assert self.received == 'done'
            assert task.done()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('handler_block', (True, False))
    async def test_non_blocking_error_handler_applicationhandlerstop(
        self, app, recwarn, handler_block
    ):
        async def callback(update, context):
            raise RuntimeError()

        async def error_handler(update, context):
            raise ApplicationHandlerStop

        app.add_handler(TypeHandler(object, callback, block=handler_block))
        app.add_error_handler(error_handler, block=False)

        async with app:
            await app.start()
            await app.update_queue.put(1)
            await asyncio.sleep(0.05)
            await app.stop()

        assert len(recwarn) == 1
        assert recwarn[0].category is PTBUserWarning
        assert (
            str(recwarn[0].message)
            == 'ApplicationHandlerStop is not supported with asynchronously running handlers.'
        )
        assert (
            Path(recwarn[0].filename) == PROJECT_ROOT_PATH / 'telegram' / 'ext' / '_application.py'
        ), "incorrect stacklevel!"

    @pytest.mark.parametrize(['block', 'expected_output'], [(False, 0), (True, 5)])
    @pytest.mark.asyncio
    async def test_default_block_error_handler(self, bot, monkeypatch, block, expected_output):
        async def error_handler(*args, **kwargs):
            await asyncio.sleep(0.1)
            self.count = 5

        app = Application.builder().token(bot.token).defaults(Defaults(block=block)).build()
        app.add_handler(TypeHandler(object, self.callback_raise_error))
        app.add_error_handler(error_handler)
        await app.process_update(1)
        await asyncio.sleep(0.05)
        assert self.count == expected_output
        await asyncio.sleep(0.1)
        assert self.count == 5

    #
    # @pytest.mark.parametrize(
    #     ['block', 'expected_output'], [(True, 'running async'), (False, None)]
    # )
    # def test_default_run_async(self, monkeypatch, app, block, expected_output):
    #     def mock_run_async(*args, **kwargs):
    #         self.received = 'running async'
    #
    #     # set defaults value to app.bot
    #     app.bot._defaults = Defaults(block=block)
    #     try:
    #         app.add_handler(MessageHandler(filters.ALL, lambda u, c: None))
    #         monkeypatch.setattr(app, 'block', mock_run_async)
    #         app.process_update(self.message_update)
    #         assert self.received == expected_output
    #
    #     finally:
    #         # reset defaults value
    #         app.bot._defaults = None
    #
    # def test_async_handler_error_handler_that_raises_error(self, app, caplog):
    #     handler = MessageHandler(filters.ALL, self.callback_raise_error, block=True)
    #     app.add_handler(handler)
    #     app.add_error_handler(self.error_handler_raise_error, block=False)
    #
    #     with caplog.at_level(logging.ERROR):
    #         await app.update_queue.put(self.message_update)
    #         await asyncio.sleep(0.05)
    #         assert len(caplog.records) == 1
    #         assert (
    #             caplog.records[-1].getMessage().startswith('An error was raised and an uncaught')
    #         )
    #
    #     # Make sure that the main loop still runs
    #     app.remove_handler(handler)
    #     app.add_handler(MessageHandler(filters.ALL, self.callback_increase_count, block=True))
    #     await app.update_queue.put(self.message_update)
    #     await asyncio.sleep(0.05)
    #     assert self.count == 1
    #
    # def test_async_handler_async_error_handler_that_raises_error(self, app, caplog):
    #     handler = MessageHandler(filters.ALL, self.callback_raise_error, block=True)
    #     app.add_handler(handler)
    #     app.add_error_handler(self.error_handler_raise_error, block=True)
    #
    #     with caplog.at_level(logging.ERROR):
    #         await app.update_queue.put(self.message_update)
    #         await asyncio.sleep(0.05)
    #         assert len(caplog.records) == 1
    #         assert (
    #             caplog.records[-1].getMessage().startswith('An error was raised and an uncaught')
    #         )
    #
    #     # Make sure that the main loop still runs
    #     app.remove_handler(handler)
    #     app.add_handler(MessageHandler(filters.ALL, self.callback_increase_count, block=True))
    #     await app.update_queue.put(self.message_update)
    #     await asyncio.sleep(0.05)
    #     assert self.count == 1

    @pytest.mark.parametrize(
        'message',
        [
            Message(message_id=1, chat=Chat(id=2, type=None), migrate_from_chat_id=1, date=None),
            Message(message_id=1, chat=Chat(id=1, type=None), migrate_to_chat_id=2, date=None),
            Message(message_id=1, chat=Chat(id=1, type=None), date=None),
            None,
        ],
    )
    @pytest.mark.parametrize('old_chat_id', [None, 1, "1"])
    @pytest.mark.parametrize('new_chat_id', [None, 2, "1"])
    def test_migrate_chat_data(self, app, message: 'Message', old_chat_id: int, new_chat_id: int):
        def call(match: str):
            with pytest.raises(ValueError, match=match):
                app.migrate_chat_data(
                    message=message, old_chat_id=old_chat_id, new_chat_id=new_chat_id
                )

        if message and (old_chat_id or new_chat_id):
            call(r"^Message and chat_id pair are mutually exclusive$")
            return

        if not any((message, old_chat_id, new_chat_id)):
            call(r"^chat_id pair or message must be passed$")
            return

        if message:
            if message.migrate_from_chat_id is None and message.migrate_to_chat_id is None:
                call(r"^Invalid message instance")
                return
            effective_old_chat_id = message.migrate_from_chat_id or message.chat.id
            effective_new_chat_id = message.migrate_to_chat_id or message.chat.id

        elif not (isinstance(old_chat_id, int) and isinstance(new_chat_id, int)):
            call(r"^old_chat_id and new_chat_id must be integers$")
            return
        else:
            effective_old_chat_id = old_chat_id
            effective_new_chat_id = new_chat_id

        app.chat_data[effective_old_chat_id]['key'] = "test"
        app.migrate_chat_data(message=message, old_chat_id=old_chat_id, new_chat_id=new_chat_id)
        assert effective_old_chat_id not in app.chat_data
        assert app.chat_data[effective_new_chat_id]['key'] == "test"

    @pytest.mark.parametrize(
        "c_id,expected",
        [(321, {222: "remove_me"}), (111, {321: {'not_empty': 'no'}, 222: "remove_me"})],
        ids=["test chat_id removal", "test no key in data (no error)"],
    )
    def test_drop_chat_data(self, app, c_id, expected):
        app._chat_data.update({321: {'not_empty': 'no'}, 222: "remove_me"})
        app.drop_chat_data(c_id)
        assert app.chat_data == expected

    @pytest.mark.parametrize(
        "u_id,expected",
        [(321, {222: "remove_me"}), (111, {321: {'not_empty': 'no'}, 222: "remove_me"})],
        ids=["test user_id removal", "test no key in data (no error)"],
    )
    def test_drop_user_data(self, app, u_id, expected):
        app._user_data.update({321: {'not_empty': 'no'}, 222: "remove_me"})
        app.drop_user_data(u_id)
        assert app.user_data == expected

    # TODO:
    #  * Test stop() with updater running
    #  * Test run_polling/webhook
    #  * Test concurrent updates
    #  * Test create_task