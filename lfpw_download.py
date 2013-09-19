#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Helper program to (robustly) download images from LFPW
http://homes.cs.washington.edu/~neeraj/databases/base/databases/lfpw/

Requires TwistedMatrix,
the cool python event-driven networking engine
http://twistedmatrix.com

and python-magic
https://github.com/ahupp/python-magic


Code inspired by
http://technicae.cogitat.io
/2008/06/async-batching-with-twisted-walkthrough.html
and
http://as.ynchrono.us/2006/05/limiting-parallelism_22.html
and
http://laconsigna.wordpress.com/2012/11/23/script-for-downloading-lfpw

We assume that the proper csv files are on the side of this python program.
USAGE: Simply launch the program and enjoy the download bars progress.
"""

from __future__ import print_function

import os.path
import csv

from twisted.internet import reactor, defer, task
from twisted.web.client import downloadPage

import magic

from progressbar import ProgressBar, Percentage, Bar, ETA, AdaptiveETA
from colors import red, green, blue

counter = 0
fail_counter = 0
progress_bar_widgets = [
    Percentage(),
    ' ', Bar(),
    ' ', ETA(),
    ' ', AdaptiveETA()
]

progress_bar = None
errors = []


class FakeFailure:
    """
    Helper class that emulates
    http://twistedmatrix.com
    /documents/current/api/twisted.python.failure.Failure.html
    """

    def __init__(self, message):
        self.message = message

    def getErrorMessage(self):
        return self.message


def non_thread_safe_increment(url, value, error):
    """
    We assume this method is called in a thread safe way
    """
    #print("Counter incremented from ", threading.current_thread())
    global counter_lock, counter, fail_counter, progress_bar
    counter += 1
    if value is not None:
        print("Value == ", value)
    if error is not None:
        errors.append((url, error))
        fail_counter += 1
    progress_bar.update(counter)
    return


def increment_progress_bar(file_path, url, value, error):

    if error is None and os.path.exists(file_path):
        mime = magic.from_file(file_path, mime=True)
        if not mime.startswith("image"):
            os.remove(file_path)
            message = "Removed file %s because its mime type is %s" \
                      % (os.path.basename(file_path), mime)
            error = FakeFailure(message)
        elif mime.endswith("jpeg"):
            # all good, nothing to do
            pass
        else:
            new_extension = "." + mime.split("/")[1]
            new_file_path = os.path.splitext(file_path)[0] + new_extension
            os.rename(file_path, new_file_path)
    else:
        # all is good !
        pass

    reactor.callFromThread(non_thread_safe_increment,
                           url, value, error)
    return


def downloads_finished():

    global counter, fail_counter, errors, progress_bar

    progress_bar.finish()

    print(green("Obtained %i out of %i images, %i could not be retrieved"
          % (counter - fail_counter, counter, fail_counter)))

    for url, error in errors:
        print("Error", red(error.getErrorMessage()),
              "at url", blue(url))

    print(green("Obtained %i out of %i images, %i could not be retrieved"
          % (counter - fail_counter, counter, fail_counter)))

    return


def twisted_parallel(iterable, count, callable, *args, **named):
    """
    From
    http://as.ynchrono.us/2006/05/limiting-parallelism_22.html
    """
    coop = task.Cooperator()
    work = (callable(elem, *args, **named) for elem in iterable)
    return defer.DeferredList([coop.coiterate(work) for i in xrange(count)])


def download_url((url, file_path)):
    d = downloadPage(url, file_path, timeout=10)
    d.addCallbacks(
        lambda value: increment_progress_bar(file_path, url, value, None),
        lambda error: increment_progress_bar(file_path, url, None, error)
    )

    return d


def download_urls(urls, save_path):
    """
    Based on http://twistedmatrix.com/documents/12.3.0/web/examples/dlpage.py
    """
    assert os.path.isdir(save_path)

    base_name = os.path.basename(save_path)
    print("Starting to download all %i %s images"
          % (len(urls), base_name))

    global counter, fail_counter, errors, progress_bar
    progress_bar = ProgressBar(widgets=progress_bar_widgets,
                               maxval=len(urls))
    counter = 0
    fail_counter = 0
    progress_bar.start()

    urls_and_file_paths = []
    for i, url in enumerate(urls):
        # downloadPage returns a defered value
        url_file_name = os.path.basename(url)
        file_name = "%s_%i_%s" % (base_name, i, url_file_name)
        if not file_name.endswith(".jpg"):
            file_name += ".jpg"
        file_path = os.path.join(save_path, file_name)
        urls_and_file_paths.append((url, file_path))
    # end of "for each url"

    max_parallel_downloads = 10
    d = twisted_parallel(urls_and_file_paths,
                         max_parallel_downloads,
                         download_url)
    return d


def collect_urls_from_csv(cvs_filepath):
    urls = []
    with open(cvs_filepath, "r") as csvfile:
        train_reader = csv.reader(csvfile, delimiter='\t')
        for row in train_reader:
            if len(row) > 2 and row[1] == "average":
                urls.append(row[0])
            else:
                # we skip the url copies
                pass
        # end of "for each row in csv file"

    return urls


def read_urls(base_name="kbvt_lfpw_v1_"):

    train_cvs_filepath = base_name + "train.csv"
    test_cvs_filepath = base_name + "test.csv"

    train_urls = collect_urls_from_csv(train_cvs_filepath)
    test_urls = collect_urls_from_csv(test_cvs_filepath)
    return train_urls, test_urls


def check_download_folder_exist():
    """
    If download folders do no exist, will create them
    """

    if not os.path.exists("./train"):
        os.mkdir("./train")
        print("Created downloads folder ./train")

    if not os.path.exists("./test"):
        os.mkdir("./test")
        print("Created downloads folder ./test")

    return


def reactor_main(train_urls, test_urls):

    get_test_data = lambda: download_urls(test_urls, "./test")
    get_train_data = lambda: download_urls(train_urls, "./train")

    def finish_and_stop(value):
        downloads_finished()
        reactor.stop()
        return

    def get_train_data_and_stop(value):
        downloads_finished()
        d = get_train_data()
        d.addCallbacks(finish_and_stop,
                       reactor.stop)
        return

    def print_error_and_stop(error):
        print(error)
        reactor.stop()
        return

    d = get_test_data()
    d.addCallbacks(get_train_data_and_stop,
                   print_error_and_stop)
    return d


def main():

    train_urls, test_urls = read_urls()
    check_download_folder_exist()

    if False:
        # less data to download, just for testing
        train_urls = train_urls[:5]
        test_urls = test_urls[:5]

    reactor.callWhenRunning(reactor_main, train_urls, test_urls)

    reactor.run()

    downloads_finished()
    print("End of game, have a nice day !")
    return

if __name__ == "__main__":
    main()


# end of file
