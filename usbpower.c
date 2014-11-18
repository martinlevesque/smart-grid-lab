//    Software to control the "USB NET POWER 8800" usb-controlled outlet
//    Copyright Â© 2012 Jeff Epler
//
//    This program is free software; you can redistribute it and/or modify
//    it under the terms of the GNU General Public License as published by
//    the Free Software Foundation; either version 2 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU General Public License for more details.
//
//    You should have received a copy of the GNU General Public License
//    along with this program; if not, write to the Free Software
//    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <usb.h>
#include <stdarg.h>
#include <string.h>

enum { TOGGLE, ON, OFF, STATUS };

void fatal(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    exit(1);
}

struct usb_dev_handle *my_dev;

void my_usb_init(int ven, int pro, int switchId) {
    struct usb_bus *busses;
    struct usb_bus *bus;

    usb_init();
    usb_find_busses();
    usb_find_devices();

    busses = usb_get_busses();

    int cnt = 0;

    for(bus = busses; bus; bus=bus->next) {
        struct usb_device *dev;
        for(dev = bus->devices; dev; dev=dev->next) {
		//printf("listing\n");
            if(dev->descriptor.idVendor == ven
                    && dev->descriptor.idProduct == pro) 
	    {

		cnt += 1;

		if (cnt == switchId)
		{
			my_dev = usb_open(dev);

			//printf("found one...\n");

			if(!my_dev)
			    fatal("usb_open failed (errno=%s)\n", strerror(errno));
			
			return;
		}
            }
        }
    }

    fatal("could not find device\n");
}

/*

    def IsOn(self):
        # Return True if the power is currently switched on.
        ret = self.dev.ctrl_transfer(0xc0, 0x01, 0x0081, 0x0000, 0x0001)
        return ret[0] == 0xa0

    def Set(self, on):
        # If True, turn the power on, else turn it off.
        code = 0xa0 if on else 0x20
        self.dev.ctrl_transfer(0x40, 0x01, 0x0001, code, [])
*/

int is_on() {
    unsigned char res;
    int ret = usb_control_msg(my_dev, 0xc0, 1, 0x81, 0, (char*)&res, 1, 1000);
    if(ret < 0) fatal("is_on: usb_control_msg returned %d [errno: %s]\n", ret,
        strerror(errno));
    return res == 0xa0;
}

void set_status(int value) {
    char code = value ? 0xa0 : 0x20;
    int ret = usb_control_msg(my_dev, 0x40, 1, 0x1, code, NULL, 0, 1000);
    if(ret < 0) fatal("is_on: usb_control_msg returned %d [errno: %s]\n", ret,
        strerror(errno));
}


int main(int argc, char **argv) {
    int command = STATUS;

    int switchIdToControl = -1;

    if(argc == 3) 
    {
	switchIdToControl = atoi(argv[2]);

        if(!strcmp(argv[1], "on")) 
		command = ON;
        else 
	if(!strcmp(argv[1], "off")) 
		command = OFF;
        else 
	if(!strcmp(argv[1], "status")) 
		command = STATUS;
        else 
	if(!strcmp(argv[1], "toggle")) 
		command = TOGGLE;
        else 
		fatal("Unrecognized argument: %s\n", argv[1]);
    } else 
        fatal("Wrong command.\n");

    my_usb_init(0x067b, 0x2303, switchIdToControl);

    switch(command) {
    case STATUS:
        printf("%s\n", is_on() ? "ON" : "OFF");
        return 0;
    case TOGGLE:
        set_status(!is_on());
        break;
    case ON:
        set_status(1);
        break;
    case OFF:
        set_status(0);
        break;
    }
    return 0;
}

