CC=gcc
CFLAGS=-O2 -Wall
LDFLAGS=-lm

all: analytics

analytics: analytics.c
	$(CC) $(CFLAGS) analytics.c -o analytics $(LDFLAGS)

clean:
	rm -f analytics
