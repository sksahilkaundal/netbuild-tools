"""WPF layout (XAML) for the "Element Remover" button, and the labels of its lists.

Plain strings so they can be checked outside Revit; the button loads them with
``forms.WPFWindow(xaml, literal_string=True)``.  IronPython 2.7 + CPython 3.
"""

COLOURS = {"OK  ": "#1B7F2A", "WARN": "#B26A00", "FAIL": "#C62828", "": "#333333"}

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_WINDOW = '''<Window {ns}
        Title="Element Remover by Netbuild" Width="1000" Height="880" MinWidth="820" MinHeight="620"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <TextBlock x:Name="info_tb" Foreground="#555555" Margin="0,2,0,0" TextWrapping="Wrap"/>
    </StackPanel>
    <Grid DockPanel.Dock="Top" Margin="0,8,0,0" Height="240">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <GroupBox Grid.Column="0" Header="Worksets -- remove the elements on them" Margin="0,0,6,0">
        <ListBox x:Name="ws_lb" SelectionMode="Extended" Margin="2"/>
      </GroupBox>
      <GroupBox Grid.Column="1" Header="Filters -- remove the elements passing them">
        <ListBox x:Name="flt_lb" SelectionMode="Extended" Margin="2"/>
      </GroupBox>
    </Grid>
    <WrapPanel DockPanel.Dock="Top" Margin="0,6,0,0">
      <TextBlock Text="With worksets and filters both picked, remove what is" VerticalAlignment="Center"
                 Margin="0,0,8,0"/>
      <RadioButton x:Name="any_rb" GroupName="combine" VerticalAlignment="Center" Margin="0,0,12,0"
                   Content="on a workset OR passing a filter"/>
      <RadioButton x:Name="all_rb" GroupName="combine" VerticalAlignment="Center"
                   Content="on a workset AND passing a filter"/>
    </WrapPanel>
    <DockPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <TextBlock DockPanel.Dock="Left" Text="Only categories" VerticalAlignment="Center" Margin="0,0,8,0"/>
      <Button x:Name="all_cats_btn" DockPanel.Dock="Right" Content="Every category" Padding="8,1" Margin="6,0,0,0"/>
      <Button x:Name="walls_btn" DockPanel.Dock="Right" Content="Walls only" Padding="8,1" Margin="6,0,0,0"/>
      <Button x:Name="cats_btn" DockPanel.Dock="Right" Content="Pick..." Padding="8,1" Margin="6,0,0,0"/>
      <TextBox x:Name="cat_tb"/>
    </DockPanel>
    <TextBlock DockPanel.Dock="Top" Foreground="#555555" Margin="0,4,0,0" TextWrapping="Wrap"
               Text="Ctrl+Click picks several worksets / filters. Categories: blank = every category, or e.g. Walls, Doors. Elements inside model groups are taken out of their group instances, which are regrouped without them."/>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <CheckBox x:Name="groups_cb" VerticalAlignment="Center" Margin="0,0,14,0"
                Content="Elements inside model groups: ungroup, remove, regroup"/>
      <CheckBox x:Name="pinned_cb" VerticalAlignment="Center" Margin="0,0,14,0"
                Content="Remove pinned elements too (unpins them)"/>
      <CheckBox x:Name="model_cb" VerticalAlignment="Center"
                Content="Model elements only (no annotation / view-specific)"/>
    </WrapPanel>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="check_btn" Content="1. Check (plan only)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="trial_btn" Content="2. Trial run (rolls back)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="apply_btn" Content="3. Apply" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="reload_btn" Content="Reload lists" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="licence_btn" Content="Licence" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''


def window_xaml():
    return _WINDOW.format(ns=_NS)


def workset_label(w):
    """'Demolition   (5 elements)' -- '[closed]' when its elements are not loaded."""
    return u"%s   (%d element%s)%s" % (w["name"], w["elements"], "" if w["elements"] == 1 else "s",
                                       "" if w["open"] else "   [closed]")


def filter_label(f):
    """'To Remove   (rules on Walls, Doors)' or 'Pick list   (saved selection, 4 elements)'."""
    if f["kind"] == "selection":
        return u"%s   (saved selection, %d element%s)" % (f["name"], f["elements"], "" if f["elements"] == 1 else "s")
    return u"%s   (rules on %s)" % (f["name"], ", ".join(f["categories"]) or "no categories")


def report_lines(checks, lines):
    """[(colour, text)] for the report list: the checks (coloured by result), then the detail lines."""
    out = [(COLOURS[c.mark], str(c)) for c in checks]
    return out + [(COLOURS[""], l) for l in lines]
