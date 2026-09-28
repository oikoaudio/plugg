/* A process whose main thread ends while another thread keeps it alive.

   This is how a Windows host looks after Wine loses its main thread: the
   leader shows as a zombie, the process and its other threads remain. With
   "stay", the main thread keeps running instead, like a healthy host.

   SPDX-License-Identifier: GPL-3.0-or-later */
#include <pthread.h>
#include <string.h>
#include <unistd.h>

static void *linger(void *unused) {
    (void)unused;
    sleep(60);
    return NULL;
}

int main(int argc, char **argv) {
    pthread_t worker;
    pthread_create(&worker, NULL, linger, NULL);
    if (argc > 1 && strcmp(argv[1], "stay") == 0) {
        sleep(60);
        return 0;
    }
    pthread_exit(NULL);
}
