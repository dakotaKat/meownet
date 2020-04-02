#! /usr/bin/env python

###
# Author:
#     Tamer Fahmy <tamer@tammura.at>
#
# Description:
#     eyemodule.py is a Python program which extracts images and notes
#     of the eyemodule pdb files and lets you view or convert them
#     to jpeg files which are put in directories reflecting the categories.
#     It optionally creates a HTML thumbnail index of the images.
#     
#
# eyemodule.py 1.2, eyemodule pdb files image extractor
# Copyright (C) 2000  Tamer Fahmy, tamer@tammura.at
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#

"""Extract and convert the images in the eyemodule database files
into jpeg files"""

import array, getopt, os, string, struct, sys, time, tempfile
from types import IntType, StringType

try:
    from PIL import Image
except ImportError:
    # make a guess and try to import it again
    sys.path.append("/usr/lib/python/site-packages/PIL")

    try:
        import Image
    except ImportError:
        sys.stderr.write("Could not find the Python Imaging Library!\n\n" +
                         "Please check if you have installed it correctly or specify the PYTHONPATH\n" +
                         "environment variable pointing to your PIL directory if you installed it in\n" +
                         "a non-standard location.\n\n")
        sys.exit(1)
    
import PIL.JpegImagePlugin
import PIL.PngImagePlugin
import PIL.PpmImagePlugin
import PIL.TiffImagePlugin

# don't look for more plugins
PIL.Image._initialized = 1

# version info
VERSION = "1.2"

class EyeModule:
    """the EyeModule class - contains all the necessary methods to obtain images and image info"""
    
    def __init__(self, O_PATH = "eyemodule", P_PATH = "."):
        """__init__(self, O_PATH, P_PATH) -
        contructor of the EyeModule class - takes an optional path to the directory argument
        which contains the eyemodule databases and an optional path to the directory containing the pdb files."""

        assert (type(O_PATH) == StringType) and (type(P_PATH) == StringType)
        
        # the header length of each image
        self.HEADER_LENGTH = 58

        # initialize the file instances
        self.__emDB_fd     = None
        self.__emVGADB_fd  = None
        self.__emNoteDB_fd = None

        # sanity checks if directory exists and if yes if it is a directory
        if not os.path.exists(O_PATH):
            try:
                os.mkdir(O_PATH)
            except Exception, error:
                raise Exception(str(error) + "\n")
        elif not os.path.isdir(O_PATH):
            raise Exception("Could not create directory " + O_PATH + "!\n")

        if not os.path.exists(P_PATH):
            raise Exception("Could not find directory " + P_PATH + "!\n")
        elif not os.path.exists(os.path.join(P_PATH, "eyemoduleDB.pdb"))    or \
             not os.path.exists(os.path.join(P_PATH, "eyemoduleVGADB.pdb")) or \
             not os.path.exists(os.path.join(P_PATH, "eyemoduleNoteDB.pdb")):
            raise Exception("Could not find the necessary .pdb files!\n")

        # change to the directory where the images should be extracted to
        os.chdir(O_PATH)

        # set the current image number to zero
        self.__cur_image = 0

        # open the *DB.pdb files for reading
        print os.path.join(P_PATH, "eyemoduleDB.pdb")
        self.__emDB_fd     = open(os.path.join(P_PATH, "eyemoduleDB.pdb"), "r")
        self.__emVGADB_fd  = open(os.path.join(P_PATH, "eyemoduleVGADB.pdb"), "r")
        self.__emNoteDB_fd = open(os.path.join(P_PATH, "eyemoduleNoteDB.pdb"), "r")

        # go to byte 52 containing the location of the appinfo in the pdb file
        # read the next 4 bytes
        self.__emDB_fd.seek(52)
        appinfo_start = struct.unpack("> L", self.__emDB_fd.read(4))[0]

        # go to byte 76 containing the number of records in the DB file
        # read the next 2 bytes
        self.__emDB_fd.seek(76)
        self.__record_cnt = struct.unpack("> 2s", self.__emDB_fd.read(2))
        self.__record_cnt = self.__str_to_Word(self.__record_cnt[0])
        
        # create an empty record data offsets dict
        self.__rec_data_offset_dict = {}

        # get the record data offsets and corresponding categories
        # a category is represented by the least significant four bits 
        for i in range(self.__record_cnt):
            rec_data = struct.unpack("> L B 3s", self.__emDB_fd.read(8))
            self.__rec_data_offset_dict[rec_data[0]] = (rec_data[1] & 0x0F)

        # create the image list and sort it
        self.__images = self.__rec_data_offset_dict.keys()
        self.__images.sort()
        
        # get the names of the categories
        self.__category_names = []
        self.__emDB_fd.seek(appinfo_start + 2)
        category = self.__emDB_fd.read(16)
        
        while ord(category[0]) != 0 and self.__emDB_fd.tell() < self.__images[0]:
            self.__category_names.append(category[:string.index(category, "\0")])
            category = self.__emDB_fd.read(16)

        # go to byte 76 containing the number of records in the VGADB file
        # read the next 2 bytes
        self.__emVGADB_fd.seek(76)
        self.__vga_record_cnt = struct.unpack("> 2s", self.__emVGADB_fd.read(2))
        self.__vga_record_cnt = self.__str_to_Word(self.__vga_record_cnt[0])

        # create an empty record data offsets dict for the color images
        self.__rec_data_offset_vga_dict = {}

        # get the record data offsets of the color images - step by 24 as
        # every color image is made up of 24 records
        for i in range(0, self.__vga_record_cnt, 24):
            rec_data = struct.unpack("> L B 3s", self.__emVGADB_fd.read(8))
            self.__rec_data_offset_vga_dict[self.__str_to_Long(rec_data[2])] = rec_data[0]

            # go to the next image record - bypass 184=24*8-8 bytes
            self.__emVGADB_fd.seek(self.__emVGADB_fd.tell() + 184)

        # go to byte 76 containing the number of records in the NoteDB file
        # read the next 2 bytes
        self.__emNoteDB_fd.seek(76)
        self.__note_record_cnt = struct.unpack("> 2s", self.__emNoteDB_fd.read(2))
        self.__note_record_cnt = self.__str_to_Word(self.__note_record_cnt[0])

        # create an empty record data offsets dict for the color images
        self.__rec_data_offset_note_dict = {}

        # get the record data offsets of the notes
        for i in range(self.__note_record_cnt):
            rec_data = struct.unpack("> L B 3s", self.__emNoteDB_fd.read(8))
            self.__rec_data_offset_note_dict[self.__str_to_Long(rec_data[2])] = rec_data[0]


    def __del__(self):
        """__del__(self) - destructor of the EyeModule class"""
        self.cleanup()


    def cleanup(self):
        """close(self) - close the database files"""
        if self.__emDB_fd:
            self.__emDB_fd.close()

        if self.__emVGADB_fd:
            self.__emVGADB_fd.close()

        if self.__emNoteDB_fd:
            self.__emNoteDB_fd.close()


    def __str_to_Word(self, str):
        """__str_to_Word(self, str) -> word
        converts a 2-byte string into a word"""

        assert type(str) == StringType and len(str) == 2
        
        return (ord(str[0]) << 8) + ord(str[1])


    def __str_to_Long(self, str):
        """__str_to_Long(self, str) -> word
        converts a 3 or 4-byte string into a long"""

        assert type(str) == StringType and (len(str) == 3 or len(str) == 4)

        if len(str) == 3:
            return long((ord(str[0]) << 16) + (ord(str[1]) << 8) + ord(str[2]))
        else:
            return long((ord(str[0]) << 24) + (ord(str[1]) << 16) + \
                   (ord(str[2]) << 8)  + ord(str[3]))
    

    def _decode_image_Grayscale(self, img_data, img_width, img_height):
        """_decode_image_Grayscale(self, img_data, img_width, img_height) -> Image
        decodes given _grayscale_ image"""

        assert type(img_data)   == StringType
        assert type(img_width)  == IntType
        assert type(img_height) == IntType

        # create a new Image with 8bit grayscale color
        image = PIL.Image.new("L", (img_width, img_height))

        # array to store the RGB pixel values into
        img_array = array.array('B')

        for value in img_data:
            pixel1 = 255 - (ord(value) & 0xF0) 
            pixel2 = 255 - ((ord(value) & 0x0F) << 4)

            img_array.fromlist([pixel1, pixel2])
            
        return PIL.Image.frombytes("L", (img_width, img_height), img_array.tostring())


    def _decode_image_Color(self, img_data, img_width, img_height):
        """_decode_image_Color(img_data, img_width, img_height) -> Image
        decodes given _color_ image"""

        assert type(img_data)   == StringType
        assert type(img_width)  == IntType
        assert type(img_height) == IntType

        # array to store the RGB pixel values into
        img_array = array.array('B')

        for pos in xrange(4, len(img_data), 4):
            # skip pdb list info
            if not pos % 6404:
                continue

            # get the YUV information for 2 pixels
            U, Y1, V, Y2 = ord(img_data[pos]),     ord(img_data[pos + 1]), \
                           ord(img_data[pos + 2]), ord(img_data[pos + 3])

            img_array.fromlist([Y1,U,V,Y2,U,V])

        img = PIL.Image.frombytes("YCbCr", (img_width, img_height), img_array.tostring())
        
        return img.convert("RGB")


    def get_header(self, image_nr = -1):
        """get_header(self, image_nr) -> header_dict
        extracts the header information from the given image number and returns a dictionary"""

        assert type(image_nr) == IntType

        if image_nr == -1:
            image_nr = self.__cur_image
        elif image_nr < self.__record_cnt:
            self.__cur_image = image_nr
        else:
            return None

        # get the header from the eyemoduleDB.pdb file
        self.__emDB_fd.seek(self.__images[image_nr])
        header = self.__emDB_fd.read(self.HEADER_LENGTH)
        
        # create the header dictionary
        header_dict = {}

        # create a header tuple from the header in big endian order
        header_tuple = struct.unpack("> 32s B B L L 2s 2s L 2s 2s 2s 2s", header)

        # get the name of the image as it appears in the image list
        header_dict["Name"] = header_tuple[0][:string.index(header_tuple[0], "\0")]

        # get the version number
        header_dict["version"] = header_tuple[1]

        # get the type
        header_dict["Type"] = header_tuple[2]

        # 0 if no VGA data
        header_dict["firstVGARecUID"] = header_tuple[3]

        # 0 if no note text
        header_dict["noteUID"] = header_tuple[4]

        # Scrolled X position
        header_dict["lastPosX"] = self.__str_to_Word(header_tuple[5])

        # Scrolled Y position
        header_dict["lastPosY"] = self.__str_to_Word(header_tuple[6])

        # Date/Time created (seconds since 1/1/1904)
        time_Offset = long(time.mktime((1904, 1, 1, 0, 0, 0, 0, 0, 0)))
        header_dict["created"] = time.ctime(header_tuple[7] + time_Offset)

        # 0xFFFF = No anchor
        header_dict["anchorX"] = self.__str_to_Word(header_tuple[8])

        # 0xFFFF = No anchor
        header_dict["anchorY"] = self.__str_to_Word(header_tuple[9])

        # Width of image in pixels, word aligned (320)
        header_dict["Width"] = self.__str_to_Word(header_tuple[10])

        # Height of image in pixels (240)
        header_dict["Height"] = self.__str_to_Word(header_tuple[11])

        return header_dict


    def get_image(self, image_nr = -1):
        """get_image(self, image_nr) -> Image
        extracts the desired image and returns it"""

        assert type(image_nr) == IntType

        if image_nr == -1:
            image_nr = self.__cur_image
        elif image_nr < self.__record_cnt:
            self.__cur_image = image_nr
        else:
            return None

        header = self.get_header(self.__cur_image)

        # calculates the byte length of the picture
        img_length = (header["Width"] * header["Height"])

        # output some information
        sys.stdout.write(`image_nr + 1` + ". " + header["Name"] + \
                         "  (" + `header["Width"]` + "x" + `header["Height"]` + ")" + \
                         "  Cat: " + self.__category_names[self.__rec_data_offset_dict[self.__images[image_nr]]] + \
                         "  created: " + `header["created"]` + "\n")

        # check if it is a colored image
        if header["firstVGARecUID"]:
            # go to the position of the desired image
            self.__emVGADB_fd.seek(self.__rec_data_offset_vga_dict[header["firstVGARecUID"]])

            # get the data for a 320x240 color image - i.e. 153696=(320*240)*2+24*4 bytes
            img_data = self.__emVGADB_fd.read(153696)

            # decode a color image
            return self._decode_image_Color(img_data, header["Width"], header["Height"])
        else:
            # go to the position of the desired image
            self.__emDB_fd.seek(self.__images[image_nr] + self.HEADER_LENGTH)
            img_data = self.__emDB_fd.read(img_length / 2)

            # decode a grayscale image
            return self._decode_image_Grayscale(img_data, header["Width"], header["Height"])


    def max_image_nr(self):
        """max_image_nr(self) -> int
        returns the maximum image number"""

        return self.__record_cnt


    def get_cur_image_nr(self):
        """get_cur_image_nr(self) -> int
        returns the current image number"""

        return self.__cur_image

    
    def get_next_image(self):
        """get_next_image(self) -> Image
        returns the next image of the image list"""

        # increase the current image counter if applicable and return the
        # image at that position
        if (self.__cur_image + 1) < self.__record_cnt:
            self.__cur_image = self.__cur_image + 1
            return self.get_image(self.__cur_image)
        else:
            return None


    def get_previous_image(self):
        """get_previous_image(self) -> Image
        returns the previous image of the image list"""

        # decrease the current image counter if applicable and return the
        # image at that position
        if (self.__cur_image - 1) > 0:
            self.__cur_image = self.__cur_image - 1
            return self.get_image(self.__cur_image)
        else:
            return None


    def view_image(self, image_nr = -1, format = "jpg"):
        """view_image(self, image_nr, format) -
        show the desired image in the desired format"""

        assert type(image_nr) == IntType
        assert type(format)   == StringType

        if image_nr == -1:
            image_nr = self.__cur_image
        elif image_nr < self.__record_cnt:
            self.__cur_image = image_nr
        else:
            return None

        im = self.get_image(image_nr)
        file = tempfile.mktemp()
        im.save(file + "." + format)
        os.system("(%s %s.%s; rm -f %s.%s)&" % ("xv", file, format, file, format))


    def view_all_images(self, format = "jpg"):
        """view_all_images(self, format) -
        shows all images in the desired format"""

        assert type(format) == StringType

        for image_nr in range(self.max_image_nr()):
            im = self.get_image(image_nr)
            file = tempfile.mktemp()
            im.save(file + "." + format)
            os.system("(%s %s.%s; rm -f %s.%s)&" % ("xv", file, format, file, format))


    def extract_image(self, image_nr = -1, format = "jpg"):
        """extract_image(self, image_nr, format) -
        extracts the desired image in the desired format"""

        assert type(image_nr) == IntType
        assert type(format)   == StringType

        if image_nr == -1:
            image_nr = self.__cur_image
        elif image_nr < self.__record_cnt:
            self.__cur_image = image_nr
        else:
            return None

        # get the header
        header = self.get_header(image_nr)

        # get the name of the category
        category = self.__category_names[self.__rec_data_offset_dict[self.__images[image_nr]]]

        # check if the category directory already exists
        if not os.path.exists(category):
            try:
                os.mkdir(category)
            except Exception, error:
                raise Exception(str(error) + "\n")

        # change into it
        os.chdir(category)

        # some conversions for correct filename handling
        filename = string.replace(header["Name"], "/", "-")
        filename = string.replace(filename, "\\", "-")
        filename = string.replace(filename, ":", "-")

        try:
            # check if the image has a note attached and extract it
            if header["noteUID"]:
                # go to the position of the desired note
                self.__emNoteDB_fd.seek(self.__rec_data_offset_note_dict[header["noteUID"]])
                note_fd = open(header["Name"] + ".txt", "w")

                # extract the text
                c = self.__emNoteDB_fd.read(1)
                while c != "\0":
                    note_fd.write(c)
                    c = self.__emNoteDB_fd.read(1)

                note_fd.close()
            
            self.get_image(image_nr).save(filename + "." + format)
        except Exception, error:
            raise Exception(str(error) + "\n")

        os.chdir("..")


    def extract_all_images(self, format = "jpg"):
        """extract_all_images(self, format) -
        extracts all images in the desired format"""

        for image_nr in range(self.max_image_nr()):
            self.extract_image(image_nr, format)

    def list_images(self):
        """list_images(self) -
        lists all images"""

        sys.stdout.write("\nImages in the pdb files:\n\n")
        
        for image_nr in range(self.max_image_nr()):
            header = self.get_header(image_nr)
            # output some information
            sys.stdout.write(`image_nr + 1` + ". " + header["Name"] + \
                             " (" + `header["Width"]` + "x" + `header["Height"]` + ")" + \
                             " Cat: " + self.__category_names[self.__rec_data_offset_dict[self.__images[image_nr]]] + \
                             " created: " + `header["created"]` + "\n")

        sys.stdout.write("\n")

# outputs a usage message
def usage():
    sys.stdout.write(os.path.basename(sys.argv[0]) + " " + VERSION + ""
                     "\nUsage: " + os.path.basename(sys.argv[0]) + " [options]"
                     "\n\nwhere options include:\n"
                     "\n-l, --list           \tlist images in the pdb files without extracting"
                     "\n-d, --dir=PATH       \tpath to image directory [default: ~/eyemodule]"
                     "\n-p, --pdb-dir=PATH   \tpath to the pdb files [default: current directory]"
                     "\n-e, --extract=NUMBER \textract single image [default: extract all images]"
                     "\n-b, --view-nr=NUMBER \tview a single image"
                     "\n-a, --view-all       \tview all images"
                     "\n-f, --format         \tformat of saved images [default: jpg]"
                     "\n                     \t                 [valid options: jpg, png, ppm, tiff]"
                     "\n-t, --thumbnail      \tcreate a HTML thumbnail index"
                     "\n-h, --help           \tissue this message"
                     "\n-v, --version        \tprint version and exit"
                     "\n\nPlease report bugs to <tamer@tammura.at>.\n")


# creates the html thumbnail index
def create_thumbnail_index(O_PATH):
    sys.stdout.write("\nCreating thumbnail index... ")

    os.chdir(O_PATH)
    index_fd = open("eyemodule.html", "w")

    # create the HTML main index header
    index_fd.write(
        "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0 Transitional//EN\">\n"
        "<HTML>\n\t<HEAD>\n\t\t<TITLE>EyeModule Thumbnail Index</TITLE>\n"
        "\t\t<meta name=\"generator\" content=\"eyemodule.py " + VERSION + " by Tamer Fahmy\">\n"
        "\t</HEAD>\n\n\n"
        "<BODY bgcolor=\"#c0c0c0\" text=\"#000000\">\n\n"
        "<div align=\"center\">\n\t<H1>EyeModule Thumbnail Index</H1><HR><BR>\n</div>\n\n<UL>\n")

    # create the entries for each directory (category)
    for directory in os.listdir(os.getcwd()):
        if os.path.isdir(directory):            
            # count the images in the directory and create a image index in
            # this directory
            img_cnt = 0
            category_fd = open(os.path.join(directory, "eyemodule_img.html"), "w")

            # create the HTML category index header
            category_fd.write(
                "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0 Transitional//EN\">\n"
                "<HTML>\n<HEAD>\n\t<TITLE>EyeModule Category: " + directory + "</TITLE>\n"
                "\t<meta name=\"generator\" content=\"eyemodule.py " + VERSION + " by Tamer Fahmy\">\n"
                "</HEAD>\n\n\n"
                "<BODY bgcolor=\"#c0c0c0\" text=\"#000000\">\n\n"
                "<div align=\"center\">\n\t<H1>EyeModule Category " + directory + "</H1><HR><BR>\n</div>\n\n<OL>\n")
            
            for file in os.listdir(directory):
                if os.path.splitext(file)[1] in (".jpg", ".png", ".ppm", ".tiff"):
                    img_cnt = img_cnt + 1
                    # insert an image
                    category_fd.write("<LI><img src=\"" + file + "\" alt=\"" + file + "\"><BR>\n" + file + " (" + \
                                      `os.path.getsize(os.path.join(directory, file))` + " bytes)<BR><BR></LI>\n")

            # create the HTML category index footer
            category_fd.write(
                "</OL>\n\n<HR>"
                "<a href=\"http://www.tammura.at/eyemodule\">eyemodule.py</a> " + VERSION + " "
                "by Tamer Fahmy on " + time.asctime(time.localtime(time.time())) + \
                "\n\n</BODY>\n</HTML>")
            
            category_fd.close()

            # insert an entry
            index_fd.write(
                "<LI>Category: <a href=\"" + directory + "/eyemodule_img.html\"> " + directory + "</a>"
                " (" + `img_cnt` + " images)<BR><BR></LI>\n")

    # create the HTML main index footer
    index_fd.write(
        "\n</UL>\n\n<HR>\n"
        "<a href=\"http://www.tammura.at/eyemodule\">eyemodule.py</a> " + VERSION + " "
        "by Tamer Fahmy on " + time.asctime(time.localtime(time.time())) + \
        "\n\n</BODY>\n</HTML>")

    index_fd.close()
    sys.stdout.write("done.\n")


# the main function
def main():

    ## initialize with default values
    # no listing mode as default
    LIST_ONLY = 0

    # directory where images should be extracted to
    OUTPUT_DIRECTORY = os.path.expanduser("~/eyemodule")

    # directory where the pdb files are located
    PDB_DIRECTORY = os.getcwd()

    # extract all images
    IMAGE_NR = -1

    # view single image
    VIEW_IMAGE = -1

    # view all images
    VIEW_ALL = 0

    # the image format to save the pictures in
    IMAGE_FORMAT = "jpg"

    # create a thumbnail index
    THUMBNAIL = 0

    # check for options
    try:
        (options, arguments) = getopt.getopt(sys.argv[1:], "ld:p:e:b:af:thv",
                                             ["list", "dir=", "pdb-dir=", "extract=", "view-nr=",
                                              "view-all", "format=", "thumbnail", "help", "version"])
        for opt in options:
            if opt[0] in ("-l", "--list"):
                LIST_ONLY = 1
                
            elif opt[0] in ("-d", "--dir"):
                OUTPUT_DIRECTORY = os.path.abspath(os.path.expanduser(opt[1]))
                
            elif opt[0] in ("-p", "--pdb-dir"):
                PDB_DIRECTORY = os.path.abspath(os.path.expanduser(opt[1]))
                
            elif opt[0] in ("-e", "--extract"):
                try:
                    IMAGE_NR = int(opt[1])
                except ValueError, error:
                    sys.stderr.write("Error: " + opt[1] + " is not a valid number!\n\n")
                    usage()
                    sys.exit(1)
                    
            elif opt[0] in ("-b", "--view-nr"):
                try:
                    VIEW_IMAGE = int(opt[1])
                except ValueError, error:
                    sys.stderr.write("Error: " + opt[1] + " is not a valid number!\n\n")
                    usage()
                    sys.exit(1)
                    
            elif opt[0] in ("-a", "--view-all"):
                VIEW_ALL = 1
                
            elif opt[0] in ("-f", "--format"):
                if not opt[1] in ["jpg", "png", "ppm", "tiff"]:
                    sys.stderr.write("Error: " + opt[1] + " is not a supported image format!\n\n")
                    usage()
                    sys.exit(1)

                IMAGE_FORMAT = opt[1]
                    
            elif opt[0] in ("-t", "--thumbnail"):
                THUMBNAIL = 1
                
            elif opt[0] in ("-h", "--help"):
                usage()
                sys.exit(0)
                
            elif opt[0] in ("-v", "--version"):
                sys.stdout.write(os.path.basename(sys.argv[0]) + " " + VERSION + "\n")
                sys.exit(0)
                
    except getopt.error, error:
        usage()
        sys.exit(1)
    
    try:
        # instantiate the EyeModule class
        eyeMod = EyeModule(O_PATH = OUTPUT_DIRECTORY,
                           P_PATH = PDB_DIRECTORY)
    except Exception, error: 
        sys.stderr.write(str(error) + "\n")
        usage()
        sys.exit(1)
    
    
    if LIST_ONLY:
        eyeMod.list_images()
        eyeMod.cleanup()
        sys.exit(0)
        
    elif VIEW_IMAGE != -1:
        if (VIEW_IMAGE - 1) < 0 or (VIEW_IMAGE - 1) >= eyeMod.max_image_nr():
            sys.stderr.write("Error: " + `VIEW_IMAGE` + " is out of range!\n\n")
            eyeMod.cleanup()
            usage()
            sys.exit(1)

        eyeMod.view_image(VIEW_IMAGE - 1, IMAGE_FORMAT)
        sys.stdout.write("\n")
        eyeMod.cleanup()
        sys.exit(0)
        
    elif VIEW_ALL:
        eyeMod.view_all_images(IMAGE_FORMAT)
        eyeMod.cleanup()
        sys.exit(0)
        
    else:
        try:
            if IMAGE_NR != -1:
                if (IMAGE_NR - 1) < 0 or (IMAGE_NR - 1) >= eyeMod.max_image_nr():
                    sys.stderr.write("Error: " + `IMAGE_NR` + " is out of range!\n\n")
                    eyeMod.cleanup()
                    usage()
                    sys.exit(1)
                    
                eyeMod.extract_image(IMAGE_NR - 1, IMAGE_FORMAT)
            else:
                eyeMod.extract_all_images(IMAGE_FORMAT)

            # check if a thumbnail index should be created
            if THUMBNAIL:
                create_thumbnail_index(OUTPUT_DIRECTORY)
        
        except Exception, error: 
            sys.stderr.write(str(error) + "\n")
            eyeMod.cleanup()
            sys.exit(1)

        sys.stdout.write("\n")
        eyeMod.cleanup()

if __name__ == "__main__":
    main()
